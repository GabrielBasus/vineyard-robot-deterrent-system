import random
import numpy as np
from typing import Dict, List
import pandas as pd
import math, numpy as np
import bisect
from time import perf_counter
import matplotlib.pyplot as plt
from matplotlib.animation import FuncAnimation
from matplotlib.patches import Polygon as MplPolygon
from matplotlib.collections import LineCollection
from collections import deque

try:
    from telemetry_sim import TelemetrySim
    mon: 'TelemetrySim|None' = TelemetrySim(enabled=True)
except Exception:
    mon = None  # telemetry disabled if import fails

from ZonePartitioner import ZonePartitioner, power_cells, build_neighbors, point_in_polygon, point_to_poly_distance, health_to_weight
from SESTPP import OnlineSESTPP
from Robot import Robot, RobotProfile
from TaskGenerator_lab import TaskGenerator, TaskAssigner
import assignment_methods_lab as aml

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
                    k = (str(source_id), str(rid), qx, qy)
                    t_last = float(self._last_intervention_key_t.get(k, -1e18))
                    if (t - t_last) < min_interval_s:
                        self.intervention_msg_dropped_debounce += 1
                        continue
                    self._last_intervention_key_t[k] = t
                self.intervention_msg_count += 1
                self.intervention_bytes += self.bytes_per_intervention_msg
                self.robots[rid].ingest_intervention_event(
                    x=ev['x'], y=ev['y'], t=ev['t'],
                    weight=w, sigma=ev.get('sigma'), omega_inhib=ev.get('omega_inhib')
                )

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
                          alpha_in=0.25, alpha_cross=0.10,
                          mu_base=1e-4, bg_ema=1e-6,
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
                             sigma=sigma, omega=omega,
                             alpha_in=alpha_in, alpha_cross=alpha_cross,
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

# --- A very light “recent tasks” buffer for the plot ---

class RecentTasks:
    def __init__(self, maxlen=60):
        self.buf = deque(maxlen=maxlen)
    def extend(self, tasks):
        self.buf.extend(tasks)
    def list(self):
        return list(self.buf)

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
    NX=120, NY=96, sigma=16.0, omega=700.0, mu_base=1e-4, bg_ema=3e-4,
    # Detections near robots
    detect_rate_per_robot=0.01, detect_sigma_m=10.0,

    bird_stay_mean_s=20.0,       # how long a bird lingers near a robot (exp. mean)
    bird_detection_prob=0.10,    # per-step chance to emit a detection while present
    per_robot_cooldown_s=10.0,   # minimum time between detections for each robot
    max_detections_per_step=2,   # safety cap per step per robot
    
    # Tasks / motion
    task_replan_period_s=10.0, arrival_radius_m=3.0, hold_time_s=20.0,
    patrol_min_hotspot_score=1e-4,
    patrol_hotspot_filter_mode="absolute",
    patrol_hotspot_score_percentile=90.0,
    patrol_hotspot_keep_top_k=None,
    patrol_point_generation_mode="hotspots",
    patrol_mc_rollouts=64,
    patrol_mc_max_events_per_rollout=24,
    patrol_mc_use_excess=True,
    # Dynamic task suppression near deterrence
    deterring_suppress_radius_m=20.0,
    deterring_suppress_window_s=60.0,
    # Task refresh pruning
    task_refresh_min_score=1e-4,
    task_max_age_s=120.0,
    # Task priority tuning
    w_prio=3.0,
    prio_deterring=2.0,
    prio_patrolling=0.2,
    assigner_w_load=0.8,
    assigner_w_task_value=0.0,
    assignment_method="frozen_greedy",
    assignment_distance_cost_per_m=0.0,
    assignment_switch_penalty=0.0,
    cbba_max_rounds=25,
    cbba_epsilon=1e-9,
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
    model_deterring_budget_mode="count_per_hour",
    model_deterring_budget_utility_per_robot_per_hr=5.0,
    model_deterring_gate_policy="heuristic",
    model_deterring_sprt_alpha=0.05,
    model_deterring_sprt_beta=0.20,
    model_deterring_sprt_patch_radius_m=None,
    model_deterring_chance_threshold=0.20,
    model_deterring_min_deltaJ_per_cost=0.15,
    model_deterring_capacity_rho_max=0.85,
    model_deterring_capacity_history_window_s=3600.0,
    model_deterring_capacity_min_completed_tasks=3,
    model_deterring_capacity_fallback_budget_per_hr=None,
    min_predicted_deltaJ_for_model_deterring=0.0,
    # Planner/dispatch admission controls
    max_active_tasks_per_robot=4,
    max_active_patrolling_per_robot=2,
    max_active_model_deterring_per_robot=1,
    preempt_deterring_goals=True,
    preempt_direct_detection_goals=True,
    preempt_model_scored_goals=False,
    # Simulation mode selector
    simulation_mode="proposed",
    # Baseline toggles
    enable_patrolling=None,
    enable_intervention_feedback=None,
    include_fallback_patrol=None,
    enable_model_scored_deterring=None,
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
    export_field_debug=False,
    export_task_debug=False,
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
):
    rng = np.random.default_rng(seed)
    boundary = [(0,0),(W,0),(W,H),(0,H)]

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
            sigma=sigma, omega=omega,
            alpha_in=alpha_in, alpha_cross=alpha_cross,
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
    suppression_effect_sum = 0.0
    suppression_effect_by_mode = {}
    suppression_effect_by_source = {"direct_detection": 0.0, "model_scored": 0.0}
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

    def _process_truth_event(x, y, t_now, enqueue_tasks=True, record_metrics=True):
        nonlocal value_weighted_exposure
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
            # Only detect if within range of the owning robot
            ox, oy = pose[owner]
            if math.hypot(x - ox, y - oy) > detect_range_m:
                return
            b = robots[owner].ingest_detection(x, y, t_now)
            bus.send_boundary_events(b, source_id=owner)
            if enqueue_tasks:
                taskgen.on_detection(owner, x, y, t_now)
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

    def _merged_zone_fields():
        if not robots:
            return np.array([]), np.array([]), np.zeros((0, 0)), np.zeros((0, 0))
        rid0 = next(iter(robots.keys()))
        rob0 = robots[rid0]
        xs = np.array(rob0.m.xs, copy=True)
        ys = np.array(rob0.m.ys, copy=True)
        lam_out = np.zeros((rob0.m.ny, rob0.m.nx), dtype=float)
        mu_out = np.zeros((rob0.m.ny, rob0.m.nx), dtype=float)
        robot_ids = list(robots.keys())
        for yy, wy in enumerate(ys):
            for xx, wx in enumerate(xs):
                owner = None
                for rid in robot_ids:
                    poly = robots[rid].zone_polygon
                    if poly and point_in_polygon(float(wx), float(wy), poly):
                        owner = rid
                        break
                if owner is None:
                    owner = min(
                        robot_ids,
                        key=lambda rid: math.hypot(float(wx) - float(pose[rid][0]), float(wy) - float(pose[rid][1])),
                    )
                lam_out[yy, xx] = float(robots[owner].m.lam[yy, xx])
                mu_out[yy, xx] = float(robots[owner].m.mu[yy, xx])
        return xs, ys, lam_out, mu_out

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
            "w_task_value": float(assigner_w_task_value),
        },
    )
    next_tid = 1
    active_tasks = []     # list of dicts: {id, type, x,y,time,origin,assigned_primary,assigned_secondary,state,started_hold}
    completed_tasks = []  # same schema + state='done'
    recent_deterrences = deque(maxlen=200)  # {"x","y","t","mode","beta","sigma","omega"}
    model_deterring_accepted = 0
    model_deterring_rejected_budget = 0
    model_deterring_rejected_budget_count_mode = 0
    model_deterring_rejected_budget_utility_mode = 0
    model_deterring_budget_by_robot = {rid: deque() for rid in robots}  # entries: (t, utility)
    service_history_by_robot = {rid: deque() for rid in robots}  # entries: (t_done, service_time_s)
    direct_deterring_arrivals_by_robot = {rid: deque() for rid in robots}  # entries: t_assigned
    model_deterring_admissions_by_robot = {rid: deque() for rid in robots}  # entries: t_assigned
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
    planner_rejected_model_det_cap = 0
    planner_replaced_patrol = 0
    planner_replaced_low_utility_count = 0
    assigned_task_value_sum = 0.0
    assigned_task_value_count = 0
    assignment_solver_calls = 0
    assignment_solver_runtime_ms_total = 0.0
    assignment_solver_conflicts_resolved = 0
    assignment_solver_unassigned = 0
    assignment_solver_rounds_total = 0
    assignment_solver_bid_updates = 0
    assignment_solver_message_passes = 0
    assignment_solver_failures = 0
    assignment_solver_feasible_edges = 0
    assignment_solver_infeasible_edges = 0
    forecast_last_eval_t = -1e9
    forecast_recall_vals = []
    forecast_precision_vals = []
    forecast_lead_times = []
    forecast_hit_flags = []
    stale_goal_clears = 0
    stale_task_evictions_count = 0
    stale_task_evictions_suppression = 0
    stale_task_evictions_age = 0
    stale_task_evictions_low_intensity = 0
    predicted_deltaj_sum = 0.0
    predicted_deltaj_sum_by_source = {"direct_detection": 0.0, "model_scored": 0.0}
    queue_depth_samples = 0
    queue_depth_total_sum = 0.0
    queue_depth_patrolling_sum = 0.0
    queue_depth_deterring_sum = 0.0
    queue_depth_model_deterring_sum = 0.0
    queue_depth_total_max = 0
    queue_depth_patrolling_max = 0
    queue_depth_deterring_max = 0
    queue_depth_model_deterring_max = 0
    debug_last_local_hotspot_score_stats = []
    debug_last_local_hotspots_raw = []
    debug_last_local_hotspots_score_filtered = []
    debug_last_local_hotspots_spaced = []
    debug_last_raw_patrol_candidates = []
    debug_last_selected_patrol_tasks = []
    if model_deterring_capacity_fallback_budget_per_hr is None:
        model_deterring_capacity_fallback_budget_per_hr = model_deterring_budget_per_robot_per_hr

    def _prune_preventive_histories(now_t):
        hist_window = max(float(model_deterring_capacity_history_window_s), 1.0)
        cutoff = float(now_t) - hist_window
        for rid in robots:
            q_budget = model_deterring_budget_by_robot.get(rid, deque())
            while q_budget and float(q_budget[0][0]) < (float(now_t) - 3600.0):
                q_budget.popleft()
            model_deterring_budget_by_robot[rid] = q_budget

            q_service = service_history_by_robot.get(rid, deque())
            while q_service and float(q_service[0][0]) < cutoff:
                q_service.popleft()
            service_history_by_robot[rid] = q_service

            q_direct = direct_deterring_arrivals_by_robot.get(rid, deque())
            while q_direct and float(q_direct[0]) < cutoff:
                q_direct.popleft()
            direct_deterring_arrivals_by_robot[rid] = q_direct

            q_model = model_deterring_admissions_by_robot.get(rid, deque())
            while q_model and float(q_model[0]) < cutoff:
                q_model.popleft()
            model_deterring_admissions_by_robot[rid] = q_model

    def _preventive_capacity_state(now_t):
        nonlocal preventive_service_rate_mean_accum, preventive_direct_arrival_rate_mean_accum
        nonlocal preventive_capacity_remaining_mean_accum, preventive_capacity_sample_count
        _prune_preventive_histories(now_t)
        hist_window = max(float(model_deterring_capacity_history_window_s), 1.0)
        rho_max = max(0.0, float(model_deterring_capacity_rho_max))
        min_completed = max(1, int(model_deterring_capacity_min_completed_tasks))
        remaining = {}
        ready = {}
        service_rates = {}
        direct_rates = {}
        remain_vals = []
        service_vals = []
        direct_vals = []
        for rid in robots:
            q_service = service_history_by_robot.get(rid, deque())
            service_times = [float(st) for (_td, st) in q_service if float(st) > 1e-9]
            if len(service_times) >= min_completed:
                mean_service = float(np.mean(service_times))
                mu_r = 3600.0 / max(mean_service, 1e-9)
                lam_direct = 3600.0 * float(len(direct_deterring_arrivals_by_robot.get(rid, deque()))) / hist_window
                lam_model = 3600.0 * float(len(model_deterring_admissions_by_robot.get(rid, deque()))) / hist_window
                lam_prev_max = max(0.0, rho_max * mu_r - lam_direct)
                rem = max(0.0, lam_prev_max - lam_model)
                ready[rid] = True
                remaining[rid] = float(rem)
                service_rates[rid] = float(mu_r)
                direct_rates[rid] = float(lam_direct)
                remain_vals.append(float(rem))
                service_vals.append(float(mu_r))
                direct_vals.append(float(lam_direct))
            else:
                ready[rid] = False
                service_rates[rid] = float("nan")
                direct_rates[rid] = float("nan")
                if str(model_deterring_budget_mode).strip().lower() == "count_per_hour":
                    q_budget = model_deterring_budget_by_robot.get(rid, deque())
                    rem = max(0.0, float(model_deterring_capacity_fallback_budget_per_hr) - float(len(q_budget)))
                else:
                    rem = float("nan")
                remaining[rid] = float(rem)
                if np.isfinite(rem):
                    remain_vals.append(float(rem))
        preventive_service_rate_snapshot.update(service_rates)
        preventive_direct_arrival_rate_snapshot.update(direct_rates)
        preventive_capacity_remaining_snapshot.update(remaining)
        preventive_capacity_ready_snapshot.update(ready)
        if remain_vals or service_vals or direct_vals:
            preventive_capacity_sample_count += 1
            preventive_capacity_remaining_mean_accum += float(np.mean(remain_vals)) if remain_vals else 0.0
            preventive_service_rate_mean_accum += float(np.mean(service_vals)) if service_vals else 0.0
            preventive_direct_arrival_rate_mean_accum += float(np.mean(direct_vals)) if direct_vals else 0.0
        return remaining, ready

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

    def _spawn_and_assign_new_tasks(now_t, patrolling_only=False):
        """Pull new tasks from TaskGenerator buffer and make them persistent until completion."""
        nonlocal next_tid, model_deterring_accepted, model_deterring_rejected_budget
        nonlocal model_deterring_rejected_budget_count_mode, model_deterring_rejected_budget_utility_mode
        nonlocal planner_rejected_unassigned, planner_rejected_task_cap
        nonlocal planner_rejected_patrol_cap, planner_rejected_model_det_cap, planner_replaced_patrol
        nonlocal planner_replaced_low_utility_count, assigned_task_value_sum, assigned_task_value_count
        nonlocal assignment_solver_calls, assignment_solver_runtime_ms_total
        nonlocal assignment_solver_conflicts_resolved, assignment_solver_unassigned
        nonlocal assignment_solver_rounds_total, assignment_solver_bid_updates
        nonlocal assignment_solver_message_passes, assignment_solver_failures
        nonlocal assignment_solver_feasible_edges, assignment_solver_infeasible_edges
        nonlocal debug_last_local_hotspot_score_stats
        nonlocal debug_last_local_hotspots_raw, debug_last_local_hotspots_score_filtered
        nonlocal debug_last_local_hotspots_spaced, debug_last_raw_patrol_candidates
        nonlocal debug_last_selected_patrol_tasks
        preventive_capacity_remaining_by_robot, preventive_capacity_ready_by_robot = _preventive_capacity_state(now_t)
        # Add patrolling (periodic) at cadence / OR immediate deterring already enqueued by on_detection
        if not patrolling_only:
            pass  # (deterring tasks are added via on_detection below)
        # Produce patrolling on cadence when enabled.
        if enable_patrolling:
            busy_deterring_robots = {
                str(tr.get("assigned_primary"))
                for tr in active_tasks
                if (
                    str(tr.get("state", "")).strip().lower() == "active"
                    and str(tr.get("type", "")).strip().lower() == "deterring"
                    and tr.get("assigned_primary") is not None
                )
            }
            taskgen.periodic_patrolling(robots=robots, now_t=now_t,
                                        hotspot_top_k=5, include_fallback_patrol=include_fallback_patrol,
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
                                        min_predicted_deltaJ_for_model_deterring=float(min_predicted_deltaJ_for_model_deterring),
                                        model_deterring_gate_policy=str(model_deterring_gate_policy),
                                        model_deterring_sprt_alpha=float(model_deterring_sprt_alpha),
                                        model_deterring_sprt_beta=float(model_deterring_sprt_beta),
                                        model_deterring_sprt_patch_radius_m=model_deterring_sprt_patch_radius_m,
                                        model_deterring_chance_threshold=float(model_deterring_chance_threshold),
                                        model_deterring_min_deltaJ_per_cost=float(model_deterring_min_deltaJ_per_cost),
                                        preventive_capacity_remaining_by_robot=preventive_capacity_remaining_by_robot,
                                        preventive_capacity_ready_by_robot=preventive_capacity_ready_by_robot,
                                        replan_interval_s=float(task_replan_period_s),
                                        busy_deterring_robots=busy_deterring_robots,
                                        recent_deterrence_events=list(recent_deterrences),
                                        min_hotspot_score=float(patrol_min_hotspot_score),
                                        patrol_hotspot_filter_mode=str(patrol_hotspot_filter_mode),
                                        patrol_hotspot_score_percentile=float(patrol_hotspot_score_percentile),
                                        patrol_hotspot_keep_top_k=patrol_hotspot_keep_top_k,
                                        patrol_point_generation_mode=str(patrol_point_generation_mode),
                                        patrol_mc_rollouts=int(patrol_mc_rollouts),
                                        patrol_mc_max_events_per_rollout=int(patrol_mc_max_events_per_rollout),
                                        patrol_mc_use_excess=bool(patrol_mc_use_excess),
                                        horizon_s=float(forecast_horizon_s),
                                        profiles=profiles,
                                        spinup_by_type={"UAV": 8.0, "UGV": 0.0},
                                        weight_fn=value_weight,
                                        deterring_modes=deterring_modes)
            if bool(export_task_debug):
                patrol_debug = taskgen.patrol_debug_snapshot()
                debug_last_local_hotspot_score_stats = [
                    dict(stages.get("score_stats", {}))
                    for stages in patrol_debug.values()
                    if stages.get("score_stats")
                ]
                debug_last_local_hotspots_raw = [
                    dict(row)
                    for stages in patrol_debug.values()
                    for row in stages.get("local_hotspots_raw", [])
                ]
                debug_last_local_hotspots_score_filtered = [
                    dict(row)
                    for stages in patrol_debug.values()
                    for row in stages.get("local_hotspots_score_filtered", [])
                ]
                debug_last_local_hotspots_spaced = [
                    dict(row)
                    for stages in patrol_debug.values()
                    for row in stages.get("local_hotspots_spaced", [])
                ]
                debug_last_raw_patrol_candidates = [
                    dict(row)
                    for stages in patrol_debug.values()
                    for row in stages.get("raw_patrol_candidates", [])
                ]
            else:
                debug_last_local_hotspot_score_stats = []
                debug_last_local_hotspots_raw = []
                debug_last_local_hotspots_score_filtered = []
                debug_last_local_hotspots_spaced = []
                debug_last_raw_patrol_candidates = []
        # Figure out the delta since last persist
        # For simplicity, read the tail: anything not yet in active/completed by (x,y,time,type)
        seen_keys = {(t['type'], round(t['x'],2), round(t['y'],2), round(t['time'],0)) for t in active_tasks}
        seen_keys |= {(t['type'], round(t['x'],2), round(t['y'],2), round(t['time'],0)) for t in completed_tasks}
        active_load = {rid: 0 for rid in robots}
        active_patrol_load = {rid: 0 for rid in robots}
        active_model_det_load = {rid: 0 for rid in robots}
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

        def _task_utility_value(task_row):
            raw = task_row.get("utility", task_row.get("score", float("nan")))
            try:
                val = float(raw)
            except Exception:
                val = float("nan")
            if np.isfinite(val):
                return float(val)
            ttype_loc = str(task_row.get("type", "")).strip().lower()
            if ttype_loc == "deterring":
                return float(_predicted_deltaj_for_deterring(task_row))
            return 0.0

        def _evict_active_task(evict_tr):
            nonlocal planner_replaced_patrol, planner_replaced_low_utility_count
            rid_e = evict_tr.get("assigned_primary")
            ttype_e = str(evict_tr.get("type", "")).strip().lower()
            is_model_e = (ttype_e == "deterring" and evict_tr.get("mode") not in (None, "", "none"))
            active_tasks[:] = [tr for tr in active_tasks if tr.get("id") != evict_tr.get("id")]
            if rid_e in active_load:
                active_load[rid_e] = max(0, active_load.get(rid_e, 0) - 1)
                if ttype_e == "patrolling":
                    active_patrol_load[rid_e] = max(0, active_patrol_load.get(rid_e, 0) - 1)
                if is_model_e:
                    active_model_det_load[rid_e] = max(0, active_model_det_load.get(rid_e, 0) - 1)
            if rid_e in goal and goal.get(rid_e) is not None:
                gx, gy = goal[rid_e]
                if math.hypot(float(evict_tr.get("x", 0.0)) - gx, float(evict_tr.get("y", 0.0)) - gy) <= arrival_radius_m:
                    goal[rid_e] = None
            if ttype_e == "patrolling":
                planner_replaced_patrol += 1
            planner_replaced_low_utility_count += 1
        candidates = []
        for t in taskgen.rows()[-200:]:  # recent window
            if (not np.isfinite(t.get("x", float("nan")))) or (not np.isfinite(t.get("y", float("nan")))):
                continue
            key = (t['type'], round(t['x'],2), round(t['y'],2), round(t['time'],0))
            if key in seen_keys:
                continue
            candidates.append(dict(t))
        debug_last_selected_patrol_tasks = []

        if not candidates:
            return

        # Keep direct-detection path assignment unchanged from frozen behavior.
        direct_candidates = []
        regular_candidates = []
        for t in candidates:
            ttype = str(t.get("type", "")).strip().lower()
            is_direct = (ttype == "deterring" and t.get("mode") in (None, "", "none"))
            if is_direct:
                direct_candidates.append(t)
            else:
                regular_candidates.append(t)

        assignments: Dict[int, tuple[str, str | None]] = {}

        # 1) Frozen direct-detection path
        for idx, t in enumerate(direct_candidates):
            assigner.set_load(active_load)
            res = assigner.assign_task(t)
            assigned_primary = res and res["primary"]
            assigned_secondary = res and res["secondary"]
            if assigned_primary is None:
                planner_rejected_unassigned += 1
                assignment_solver_unassigned += 1
                continue
            assignments[id(t)] = (assigned_primary, assigned_secondary)

        # 2) Method-selected assignment for patrolling + model-scored deterrence
        if regular_candidates:
            assigner.set_load(active_load)
            eligible_map = {}
            score_map = {}

            # Shared assignment utility/cost protocol used by all assignment methods.
            # Utility = TaskAssigner score - optional dispatch costs.
            def _shared_assignment_utility(rid, task_idx):
                tloc = regular_candidates[int(task_idx)]
                s = float(assigner.score_robot_for_task(rid, tloc))
                if not math.isfinite(s):
                    return float("-inf")
                task_value = float(_task_utility_value(tloc))
                s += float(assigner_w_task_value) * task_value
                if float(assignment_distance_cost_per_m) > 0.0:
                    rx, ry = pose[rid]
                    s -= float(assignment_distance_cost_per_m) * float(
                        math.hypot(float(tloc["x"]) - rx, float(tloc["y"]) - ry)
                    )
                if float(assignment_switch_penalty) > 0.0 and goal.get(rid) is not None:
                    gx, gy = goal[rid]
                    if math.hypot(float(tloc["x"]) - gx, float(tloc["y"]) - gy) > float(arrival_radius_m):
                        s -= float(assignment_switch_penalty)
                return float(s)

            for j, t in enumerate(regular_candidates):
                cands, _scope = assigner.candidate_robot_ids(t)
                cset = set(cands)
                eligible_map[j] = cset
                for rid in cset:
                    score_map[(rid, j)] = float(_shared_assignment_utility(rid, j))

            capacity_by_robot = {
                rid: max(0, int(max_active_tasks_per_robot) - int(active_load.get(rid, 0)))
                for rid in robots
            }
            neighbors_by_robot = {
                rid: [nbr for nbr in robots[rid].neighbors if nbr in robots]
                for rid in robots
            }
            req = aml.AssignmentRequest(
                tasks=regular_candidates,
                robots=list(robots.keys()),
                capacity_by_robot=capacity_by_robot,
                score_fn=lambda rid, j: float(score_map.get((rid, j), float("-inf"))),
                eligible_fn=lambda rid, j: rid in eligible_map.get(j, set()),
                task_type_fn=lambda j: str(regular_candidates[j].get("type", "")).strip().lower(),
                neighbors_by_robot=neighbors_by_robot,
                cbba_max_rounds=int(cbba_max_rounds),
                cbba_epsilon=float(cbba_epsilon),
                protocol={
                    "name": "shared_assignment_utility_v1",
                    "assignment_distance_cost_per_m": float(assignment_distance_cost_per_m),
                    "assignment_switch_penalty": float(assignment_switch_penalty),
                    "w_load": float(assigner_w_load),
                    "assigner_w_task_value": float(assigner_w_task_value),
                    "w_prio": float(w_prio),
                    "prio_deterring": float(prio_deterring),
                    "prio_patrolling": float(prio_patrolling),
                },
            )

            t0 = perf_counter()
            res = aml.solve_assignment(str(assignment_method), req)
            dt_ms = (perf_counter() - t0) * 1000.0
            assignment_solver_calls += 1
            assignment_solver_runtime_ms_total += float(dt_ms)
            assignment_solver_conflicts_resolved += int(res.debug.get("conflicts_resolved", 0))
            assignment_solver_rounds_total += int(res.debug.get("rounds", 0))
            assignment_solver_bid_updates += int(res.debug.get("bid_updates", 0))
            assignment_solver_message_passes += int(res.debug.get("message_passes", 0))
            assignment_solver_failures += int(res.debug.get("failures", 0))
            assignment_solver_feasible_edges += int(res.debug.get("feasible_edges", 0))
            assignment_solver_infeasible_edges += int(res.debug.get("infeasible_edges", 0))

            for j, rid in res.primary_by_task_idx.items():
                if rid not in robots:
                    continue
                t = regular_candidates[int(j)]
                scored = []
                for rr in eligible_map.get(int(j), set()):
                    s = float(score_map.get((rr, int(j)), float("-inf")))
                    if math.isfinite(s):
                        scored.append((s, rr))
                scored.sort(reverse=True, key=lambda z: (z[0], str(z[1])))
                secondary = assigner.select_secondary_for_deterring(rid, scored, t)
                assignments[id(t)] = (rid, secondary)

            assignment_solver_unassigned += max(0, len(regular_candidates) - len(res.primary_by_task_idx))

        # Apply admission controls and persist assigned tasks.
        for t in candidates:
            pair = assignments.get(id(t))
            if pair is None:
                planner_rejected_unassigned += 1
                continue
            assigned_primary, assigned_secondary = pair
            if assigned_primary is None:
                planner_rejected_unassigned += 1
                continue
            t = dict(t)

            ttype = str(t.get("type", "")).strip().lower()
            is_model_det = (ttype == "deterring" and (t.get("mode") not in (None, "", "none")))
            t_utility = float(_task_utility_value(t))
            t["utility"] = float(t_utility)
            if bool(export_task_debug) and ttype == "patrolling":
                debug_last_selected_patrol_tasks.append(
                    {
                        "x": float(t.get("x", 0.0)),
                        "y": float(t.get("y", 0.0)),
                        "score": float(t.get("score", 0.0)),
                        "utility": float(t_utility),
                        "time": float(t.get("time", now_t)),
                        "assigned_primary": assigned_primary,
                    }
                )

            # Queue cap per robot: keep top-K non-direct intents by utility.
            if active_load.get(assigned_primary, 0) >= int(max_active_tasks_per_robot):
                # Keep direct-detection deterring path unchanged; cap only patrol/model-scored.
                if (ttype == "patrolling") or is_model_det:
                    evict_pool = [
                        tr for tr in active_tasks
                        if (
                            tr.get("assigned_primary") == assigned_primary
                            and str(tr.get("state", "")).strip().lower() == "active"
                            and (
                                (str(tr.get("type", "")).strip().lower() == "patrolling")
                                or (
                                    str(tr.get("type", "")).strip().lower() == "deterring"
                                    and tr.get("mode") not in (None, "", "none")
                                )
                            )
                        )
                    ]
                    if not evict_pool:
                        planner_rejected_task_cap += 1
                        continue
                    worst = min(evict_pool, key=lambda tr: _task_utility_value(tr))
                    worst_u = float(_task_utility_value(worst))
                    if t_utility <= worst_u:
                        planner_rejected_task_cap += 1
                        continue
                    _evict_active_task(worst)

            # Patrolling queue cap with utility-based replacement.
            if ttype == "patrolling" and active_patrol_load.get(assigned_primary, 0) >= int(max_active_patrolling_per_robot):
                patrol_active = [
                    tr for tr in active_tasks
                    if (
                        tr.get("assigned_primary") == assigned_primary
                        and str(tr.get("state", "")).strip().lower() == "active"
                        and str(tr.get("type", "")).strip().lower() == "patrolling"
                    )
                ]
                if patrol_active:
                    worst = min(patrol_active, key=lambda tr: _task_utility_value(tr))
                    worst_u = float(_task_utility_value(worst))
                    if t_utility <= worst_u:
                        planner_rejected_patrol_cap += 1
                        continue
                    _evict_active_task(worst)

            if is_model_det:
                # Additional cap for preventive/model-scored deterring: keep top-K by utility.
                if active_model_det_load.get(assigned_primary, 0) >= int(max_active_model_deterring_per_robot):
                    model_active = [
                        tr for tr in active_tasks
                        if (
                            tr.get("assigned_primary") == assigned_primary
                            and str(tr.get("state", "")).strip().lower() == "active"
                            and str(tr.get("type", "")).strip().lower() == "deterring"
                            and tr.get("mode") not in (None, "", "none")
                        )
                    ]
                    if not model_active:
                        planner_rejected_model_det_cap += 1
                        continue
                    worst = min(model_active, key=lambda tr: _task_utility_value(tr))
                    worst_u = float(_task_utility_value(worst))
                    if t_utility <= worst_u:
                        planner_rejected_model_det_cap += 1
                        continue
                    _evict_active_task(worst)
                # Budget gate per assigned robot.
                q = model_deterring_budget_by_robot.get(assigned_primary, deque())
                while q and float(q[0][0]) < (now_t - 3600.0):
                    q.popleft()
                spent_count = int(len(q))
                spent_utility = float(sum(float(u) for (_ts, u) in q))
                budget_mode = str(model_deterring_budget_mode).strip().lower()
                if budget_mode not in ("count_per_hour", "utility_per_hour"):
                    budget_mode = "count_per_hour"
                over_budget = False
                if budget_mode == "utility_per_hour":
                    util_budget = max(0.0, float(model_deterring_budget_utility_per_robot_per_hr))
                    over_budget = (spent_utility + max(0.0, float(t_utility))) > util_budget
                else:
                    if preventive_capacity_ready_by_robot.get(assigned_primary, False):
                        count_budget = int(model_deterring_budget_per_robot_per_hr)
                    else:
                        count_budget = int(model_deterring_capacity_fallback_budget_per_hr)
                    over_budget = spent_count >= int(count_budget)
                if over_budget:
                    model_deterring_rejected_budget += 1
                    if budget_mode == "utility_per_hour":
                        model_deterring_rejected_budget_utility_mode += 1
                    else:
                        model_deterring_rejected_budget_count_mode += 1
                    continue
                q.append((float(now_t), max(0.0, float(t_utility))))
                model_deterring_budget_by_robot[assigned_primary] = q
                model_deterring_admissions_by_robot[assigned_primary].append(float(now_t))
                model_deterring_accepted += 1
            elif ttype == "deterring":
                direct_deterring_arrivals_by_robot[assigned_primary].append(float(now_t))

            active_tasks.append({
                "id": next_tid, **t,
                "assigned_primary": assigned_primary,
                "assigned_secondary": assigned_secondary,
                "state": "active",
                "started_hold": None,    # for deterring completion
                "t_assigned": float(now_t),
            })
            active_load[assigned_primary] = active_load.get(assigned_primary, 0) + 1
            if ttype == "patrolling":
                active_patrol_load[assigned_primary] = active_patrol_load.get(assigned_primary, 0) + 1
            if is_model_det:
                active_model_det_load[assigned_primary] = active_model_det_load.get(assigned_primary, 0) + 1
            assigned_task_value_sum += float(t_utility)
            assigned_task_value_count += 1

            # Telemetry: new task spawned (and assigned)
            if mon is not None and getattr(mon, 'enabled', False):
                mon.event_task('spawn', active_tasks[-1])
                if assigned_primary is not None:
                    mon.event_task('assign', active_tasks[-1])

            # If robot has no current goal, give it this one
            if assigned_primary and goal[assigned_primary] is None:
                goal[assigned_primary] = (t["x"], t["y"])
                if debug_movement:
                    print(f"[goal] {assigned_primary} -> ({t['x']:.1f},{t['y']:.1f}) type={t['type']}")
            next_tid += 1

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
                        _process_truth_event(x, y, t_w, enqueue_tasks=False, record_metrics=False)
                        _spawn_offspring(x, y, t_w)
                    else:
                        truth_suppressed_events += 1

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
                        _process_truth_event(x, y, te, enqueue_tasks=False, record_metrics=False)
                        _spawn_offspring(x, y, te)
                    else:
                        truth_suppressed_events += 1
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

    def _predicted_deltaj_for_deterring(tr):
        # Use task score when available; otherwise estimate from local excess field.
        raw_score = float(tr.get("score", 0.0))
        if np.isfinite(raw_score) and raw_score > 0.0:
            return float(raw_score)
        x = float(tr.get("x", 0.0))
        y = float(tr.get("y", 0.0))
        rid = tr.get("robot_id")
        if rid not in robots:
            return 0.0
        rob = robots[rid]
        try:
            iy, ix = rob.m.world_to_idx(x, y)
            field_excess = max(0.0, float(rob.m.lam[iy, ix] - rob.m.mu[iy, ix]))
        except Exception:
            field_excess = 0.0
        mode = tr.get("mode")
        params = deterring_modes.get(mode, {}) if mode else {}
        beta_u = float(params.get("beta", getattr(rob.m, "alpha_inhib", 0.0)))
        omega_u = float(params.get("omega", getattr(rob.m, "omega_inhib", 1.0)))
        delta_a = float(getattr(rob.m, "dx", 1.0) * getattr(rob.m, "dy", 1.0))
        estimate = field_excess * beta_u * omega_u * delta_a
        return float(max(0.0, estimate))

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

    while t <= t_end:
        # 1) Optional: trigger-only repartition on health threshold
        if any(profiles[rid].health <= health_threshold for rid in profiles):
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
                    print(f"[zone@t={t:.1f}] {rid0} area={area:.2f}")
            for r in robots_def:
                rid = r['id']
                robots[rid].update_zone(id_to_cell.get(rid, []))   # UAVs: []
                robots[rid].update_neighbors(partitioner.neighbors_for_id(rid))
                if mon is not None and getattr(mon, 'enabled', False):
                    mon.set_zone(rid, id_to_cell.get(rid, []), t=t)


        # 2) Ground-truth event generation (or legacy local detections)
        if use_ground_truth:
            # Base events sampled from value map
            if w_cdf is not None:
                area = float(W * H)
                w_mean = float(w_shape[4].mean()) if w_shape is not None else 1.0
                lam_base = mu_true * w_mean * area
                n_base = rng.poisson(lam_base * dt)
                for _ in range(int(n_base)):
                    x, y = _sample_from_value_map(rng)
                    p_keep, p_suppress, p_by_mode, p_by_source = _suppression_eval(x, y, t)
                    truth_candidate_events += 1
                    suppression_effect_sum += float(p_suppress)
                    for mk, mv in p_by_mode.items():
                        suppression_effect_by_mode[mk] = float(suppression_effect_by_mode.get(mk, 0.0) + mv)
                    for sk, sv in p_by_source.items():
                        suppression_effect_by_source[sk] = float(suppression_effect_by_source.get(sk, 0.0) + sv)
                    if rng.random() <= p_keep:
                        truth_accepted_events += 1
                        _process_truth_event(x, y, t)
                        _spawn_offspring(x, y, t)
                    else:
                        truth_suppressed_events += 1

            # Process scheduled offspring up to current time
            if truth_queue:
                due = []
                future = []
                for ev in truth_queue:
                    (x, y, te) = ev
                    if te <= t:
                        due.append(ev)
                    else:
                        future.append(ev)
                truth_queue[:] = future
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
                        _process_truth_event(x, y, te)
                        _spawn_offspring(x, y, te)
                    else:
                        truth_suppressed_events += 1
        else:
            # Legacy detections near robots (immediate deterring tasks added)
            for r in robots_def:
                rid = r['id']
                # If no bird is present
                if t >= bird_present_until[rid]:
                    if rng.random() < (1.0 - np.exp(-detect_rate_per_robot * dt)):
                        bird_present_until[rid] = t + rng.exponential(bird_stay_mean_s)

                generated = 0

                # While a bird is present, emit at most one detection this step with probability,
                # obeying a cooldown so we don't spam.
                if t < bird_present_until[rid]:
                    if rng.random() < bird_detection_prob:
                        if (t - last_detection_time[rid]) >= per_robot_cooldown_s and generated < max_detections_per_step:
                            cx, cy = pose[rid]
                            x = float(np.clip(cx + rng.normal(0.0, detect_sigma_m), 0.0, W))
                            y = float(np.clip(cy + rng.normal(0.0, detect_sigma_m), 0.0, H))

                            # Attribute to zone owner (uses id_to_cell mapping; UAVs have no zone)
                            owner = None
                            for rr in robots_def:
                                zid = rr['id']
                                zone_rr = id_to_cell.get(zid, [])
                                if zone_rr and point_in_polygon(x, y, zone_rr):
                                    owner = zid; break

                            if owner is not None:
                                b = robots[owner].ingest_detection(x, y, t)
                                bus.send_boundary_events(b, source_id=owner)
                                taskgen.on_detection(owner, x, y, t)
                                pending_event_onsets.append({"x": float(x), "y": float(y), "t": float(t), "responded": False})
                                if mon is not None and getattr(mon, 'enabled', False):
                                    mon.message(t, kind='detection', source=owner, target=owner,
                                                data={'x': x, 'y': y})

                                last_detection_time[rid] = t
                                generated += 1

        # 3) Periodic patrolling + making tasks persistent (and assigned)
        if (t - last_replan) >= task_replan_period_s:
            # Drop patrolling tasks that are close to recent deterrences.
            # Keep active deterring tasks so dispatched actions can complete.
            if recent_deterrences:
                kept = []
                removed = 0
                for tr in active_tasks:
                    keep = (
                        str(tr.get("type", "")).strip().lower() == "deterring"
                        or not any(
                            (float(ev.get("t", -1e9)) >= t - deterring_suppress_window_s)
                            and (
                                (tr["x"] - float(ev.get("x", 0.0))) ** 2
                                + (tr["y"] - float(ev.get("y", 0.0))) ** 2
                                <= deterring_suppress_radius_m ** 2
                            )
                            for ev in recent_deterrences
                        )
                    )
                    if keep:
                        kept.append(tr)
                    else:
                        removed += 1
                if removed > 0:
                    stale_task_evictions_count += int(removed)
                    stale_task_evictions_suppression += int(removed)
                active_tasks[:] = kept
            # Prune tasks that are stale or no longer supported by intensity
            kept = []
            removed_age = 0
            removed_low = 0
            for tr in active_tasks:
                age_ok = (t - tr.get("time", t) <= task_max_age_s)
                if not age_ok:
                    removed_age += 1
                    continue
                ttype = str(tr.get("type", "")).strip().lower()
                if (ttype == "patrolling") and (_task_intensity_score(tr) < task_refresh_min_score):
                    removed_low += 1
                    continue
                kept.append(tr)
            removed_total = int(removed_age + removed_low)
            if removed_total > 0:
                stale_task_evictions_count += removed_total
                stale_task_evictions_age += int(removed_age)
                stale_task_evictions_low_intensity += int(removed_low)
            active_tasks[:] = kept
            _spawn_and_assign_new_tasks(now_t=t, patrolling_only=False)
            last_replan = t

        # 4) Move robots toward goals; complete tasks on arrival rules
        for r in robots_def:
            rid = r['id']
            # If holding at a deterring site, keep holding
            if loiter_until[rid] > t:
                pass
            else:
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
                                    and bool(preempt_model_scored_goals)
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
                # If idle and there exists an active task assigned to this robot, pick nearest one
                if goal[rid] is None:
                    candidates = [tr for tr in active_tasks if tr["assigned_primary"] == rid and tr["state"]=="active"]
                    if candidates:
                        # pick nearest
                        px,py = pose[rid]
                        tid, gx, gy = min(((tr["id"], tr["x"], tr["y"]) for tr in candidates),
                                          key=lambda z: math.hypot(z[1]-px, z[2]-py))
                        goal[rid] = (gx, gy)
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
                # step
                if goal[rid] is not None:
                    _step_to(rid, goal[rid], dt)

            # Arrival / completion checks
            if goal[rid] is not None:
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
                                tr["started_hold"] = t
                                loiter_until[rid] = t + hold_time_s
                            elif t >= tr["started_hold"] + hold_time_s:
                                tr["state"] = "done"
                                tr["t_done"] = float(t)
                                t_assigned = float(tr.get("t_assigned", tr.get("time", t)))
                                service_history_by_robot[rid].append((float(t), max(0.0, float(t) - t_assigned)))
                                completed_tasks.append(tr)
                                completed_count_by_type["deterring"] += 1
                                completed_task_scores.append(float(tr.get("score", 0.0)))
                                src = _deterring_source(tr)
                                pred_v = float(_predicted_deltaj_for_deterring(tr))
                                tr["predicted_deltaJ"] = float(pred_v)
                                predicted_deltaj_sum += float(pred_v)
                                predicted_deltaj_sum_by_source[src] = float(
                                    predicted_deltaj_sum_by_source.get(src, 0.0) + float(pred_v)
                                )
                                mode = tr.get("mode")
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
                                recent_deterrences.append({
                                    "x": float(tr["x"]),
                                    "y": float(tr["y"]),
                                    "t": float(t),
                                    "mode": mode_label,
                                    "source": _deterring_source(tr),
                                    "action_id": int(tr.get("id", -1)),
                                    "beta": beta_u,
                                    "sigma": sigma_u,
                                    "omega": omega_u,
                                })
                                w = float(params.get("beta", 1.0))
                                omega_u = float(params.get("omega", robots[rid].m.omega_inhib))
                                sigma_u = float(params.get("sigma", robots[rid].m.sigma))
                                if enable_intervention_feedback:
                                    robots[rid].ingest_intervention_event(tr["x"], tr["y"], t, weight=w,
                                                                         sigma=sigma_u, omega_inhib=omega_u)
                                    b = robots[rid].intervention_boundary_events(tr["x"], tr["y"], t, weight=w)
                                    bus.send_intervention_events(
                                        b,
                                        source_id=rid,
                                        min_interval_s=float(intervention_boundary_min_interval_s),
                                        spatial_quant_m=float(intervention_boundary_spatial_quant_m),
                                        min_weight=float(intervention_boundary_min_weight),
                                    )
                                # Match nearest unresponded event onset to this deterrence arrival.
                                best_idx = None
                                best_dist = float("inf")
                                for i, ev in enumerate(pending_event_onsets):
                                    if ev["responded"] or ev["t"] > t:
                                        continue
                                    d_ev = math.hypot(tr["x"] - ev["x"], tr["y"] - ev["y"])
                                    if d_ev <= response_match_radius_m and d_ev < best_dist:
                                        best_dist = d_ev
                                        best_idx = i
                                if best_idx is not None:
                                    ev = pending_event_onsets[best_idx]
                                    pending_event_onsets[best_idx]["responded"] = True
                                    response_times.append(float(t - ev["t"]))
                                if mon is not None and getattr(mon, 'enabled', False):
                                    mon.event_task('complete', tr)

                                # remove from active and clear goal
                                active_tasks[:] = [x for x in active_tasks if x["id"] != tr["id"]]
                                goal[rid] = None
                                loiter_until[rid] = -1.0
                            break
                        else:  # patrolling completes on proximity
                            tr["state"] = "done"
                            tr["t_done"] = float(t)
                            t_assigned = float(tr.get("t_assigned", tr.get("time", t)))
                            service_history_by_robot[rid].append((float(t), max(0.0, float(t) - t_assigned)))
                            completed_tasks.append(tr)
                            completed_count_by_type["patrolling"] += 1
                            completed_task_scores.append(float(tr.get("score", 0.0)))

                            if mon is not None and getattr(mon, 'enabled', False):
                                mon.event_task('complete', tr)

                            active_tasks[:] = [x for x in active_tasks if x["id"] != tr["id"]]
                            goal[rid] = None
                            break
                    if debug_movement and not matched:
                        print(f"[stall] {rid} at ({pose[rid][0]:.1f},{pose[rid][1]:.1f}) no matching task")
                    if not matched:
                        # Task may have been pruned/reassigned while robot was en route.
                        # Clear stale goal so the robot can pick a fresh assignment next step.
                        goal[rid] = None
                        stale_goal_clears += 1

        # Telemetry: per-step poses + hotspots + periodic flush
        if mon is not None and getattr(mon, 'enabled', False):
            active_by_robot = {}
            for tr in active_tasks:
                if tr.get("state") != "active":
                    continue
                ridp = tr.get("assigned_primary")
                if ridp and ridp not in active_by_robot:
                    mode = tr.get("mode")
                    mode_txt = f"/{mode}" if mode else ""
                    active_by_robot[ridp] = f"{tr.get('type', '?')}{mode_txt}#{tr.get('id', '?')}"
            for rid in robots:
                px, py = pose[rid]
                mon.pose(t, rid, px, py)
                st = "holding" if loiter_until[rid] > t else ("moving" if goal[rid] is not None else "idle")
                if goal[rid] is None:
                    gx = gy = egx = egy = float("nan")
                    dist_goal = float("nan")
                    lane_tgt = float("nan")
                else:
                    gx, gy = goal[rid]
                    egx, egy = _effective_goal(rid, goal[rid])
                    dist_goal = float(math.hypot(px - egx, py - egy))
                    lane_tgt = float(_lane_center_for(gy))
                lane_cur = float(_lane_center_for(py))
                at_h = 1 if _is_at_headland(px) else 0
                mon.robot_diag(
                    t=t,
                    rid=rid,
                    battery=float(profiles[rid].battery),
                    state=st,
                    task=active_by_robot.get(rid, "-"),
                    goal_x=gx,
                    goal_y=gy,
                    eff_goal_x=egx,
                    eff_goal_y=egy,
                    dist_to_goal=dist_goal,
                    lane_cur=lane_cur,
                    lane_tgt=lane_tgt,
                    at_headland=at_h,
                )
                try:
                    hs = robots[rid].m.hotspots(
                        top_k=3,
                        merge_radius=max(8.0, 0.5*sigma),
                        use_excess=True,
                        mask_poly=robots[rid].zone_polygon
                    )
                    mon.hotspots(t, rid, hs)
                except Exception:
                    pass
            mon.flush_live(telemetry_dir, min_interval_s=0.5)

        # 5) Advance SESTPP time
        for rob in robots.values():
            rob.advance_time(dt)

        # 5b) Forecast quality metrics (per scenario/per baseline run)
        if use_ground_truth and ((t - forecast_last_eval_t) >= float(forecast_eval_period_s)):
            forecast_last_eval_t = t
            fut = _future_truth_events(t, float(forecast_horizon_s))
            hs = _global_hotspots(int(forecast_top_k))
            r2 = float(forecast_match_radius_m) ** 2

            if fut:
                covered = 0
                for (ex, ey, _tt) in fut:
                    if hs and any(((ex - hx) ** 2 + (ey - hy) ** 2 <= r2) for (hx, hy, _s) in hs):
                        covered += 1
                forecast_recall_vals.append(float(covered) / float(max(len(fut), 1)))

            if hs:
                hit_count = 0
                t_end_h = t + float(forecast_horizon_s)
                for (hx, hy, _s) in hs:
                    hit_t = None
                    for (ex, ey, ett) in fut:
                        if ett <= t or ett > t_end_h:
                            continue
                        if ((ex - hx) ** 2 + (ey - hy) ** 2) <= r2:
                            if hit_t is None or ett < hit_t:
                                hit_t = ett
                    if hit_t is not None:
                        hit_count += 1
                        forecast_hit_flags.append(1.0)
                        forecast_lead_times.append(float(hit_t - t))
                    else:
                        forecast_hit_flags.append(0.0)
                forecast_precision_vals.append(float(hit_count) / float(max(len(hs), 1)))

        # 6) Yield frame snapshot
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
        debug_global_hotspots = []
        debug_field_xs = []
        debug_field_ys = []
        debug_field_lam = []
        debug_field_mu = []
        if bool(export_field_debug):
            try:
                debug_global_hotspots = [
                    {"x": float(x), "y": float(y), "score": float(s)}
                    for (x, y, s) in _global_hotspots(int(forecast_top_k))
                ]
            except Exception:
                debug_global_hotspots = []
            try:
                field_xs, field_ys, field_lam, field_mu = _merged_zone_fields()
                debug_field_xs = field_xs.tolist()
                debug_field_ys = field_ys.tolist()
                debug_field_lam = field_lam.tolist()
                debug_field_mu = field_mu.tolist()
            except Exception:
                debug_field_xs = []
                debug_field_ys = []
                debug_field_lam = []
                debug_field_mu = []
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
        active_deterring = 0
        active_patrolling = 0
        active_model_deterring = 0
        for tr in active_tasks:
            if str(tr.get("state", "")).strip().lower() != "active":
                continue
            ttype = str(tr.get("type", "")).strip().lower()
            if ttype == "deterring":
                active_deterring += 1
                if tr.get("mode") not in (None, "", "none"):
                    active_model_deterring += 1
            elif ttype == "patrolling":
                active_patrolling += 1
        active_total = int(active_deterring + active_patrolling)
        queue_depth_samples += 1
        queue_depth_total_sum += float(active_total)
        queue_depth_patrolling_sum += float(active_patrolling)
        queue_depth_deterring_sum += float(active_deterring)
        queue_depth_model_deterring_sum += float(active_model_deterring)
        queue_depth_total_max = max(queue_depth_total_max, int(active_total))
        queue_depth_patrolling_max = max(queue_depth_patrolling_max, int(active_patrolling))
        queue_depth_deterring_max = max(queue_depth_deterring_max, int(active_deterring))
        queue_depth_model_deterring_max = max(queue_depth_model_deterring_max, int(active_model_deterring))
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
        robot_moving_fraction_by_robot = {
            rid: (robot_time_moving[rid] / robot_time_total[rid]) if robot_time_total[rid] > 1e-9 else float("nan")
            for rid in pose
        }
        sim_elapsed_s = max([float(v) for v in robot_time_total.values()] + [1e-9])
        final_step = (t + dt > t_end)
        if final_step:
            deterring_quality_cache = _compute_deterring_quality()
        diag_counts = getattr(taskgen, "diag_counts", {})
        _prune_preventive_histories(t)
        budget_spent_count_by_robot = {}
        budget_spent_utility_by_robot = {}
        for rid in robots:
            q = model_deterring_budget_by_robot.get(rid, deque())
            while q and float(q[0][0]) < (t - 3600.0):
                q.popleft()
            model_deterring_budget_by_robot[rid] = q
            budget_spent_count_by_robot[rid] = int(len(q))
            budget_spent_utility_by_robot[rid] = float(sum(float(u) for (_ts, u) in q))
        budget_count_vals = list(budget_spent_count_by_robot.values())
        budget_utility_vals = list(budget_spent_utility_by_robot.values())
        realized_suppression_sum = float(suppression_effect_sum)
        realized_suppression_sum_direct = float(suppression_effect_by_source.get("direct_detection", 0.0))
        realized_suppression_sum_model = float(suppression_effect_by_source.get("model_scored", 0.0))
        predicted_deltaj_sum_direct = float(predicted_deltaj_sum_by_source.get("direct_detection", 0.0))
        predicted_deltaj_sum_model = float(predicted_deltaj_sum_by_source.get("model_scored", 0.0))
        llr_samples = int(diag_counts.get("model_deterring_llr_samples", 0))
        p_event_samples = int(diag_counts.get("model_deterring_p_event_samples", 0))
        deltaj_cost_samples = int(diag_counts.get("model_deterring_deltaJ_per_cost_samples", 0))
        llr_mean = (
            float(diag_counts.get("model_deterring_llr_sum", 0.0)) / float(llr_samples)
            if llr_samples > 0 else float("nan")
        )
        llr_max = float(diag_counts.get("model_deterring_llr_max", float("nan")))
        if not np.isfinite(llr_max):
            llr_max = float("nan")
        p_event_mean = (
            float(diag_counts.get("model_deterring_p_event_sum", 0.0)) / float(p_event_samples)
            if p_event_samples > 0 else float("nan")
        )
        deltaj_per_cost_mean = (
            float(diag_counts.get("model_deterring_deltaJ_per_cost_sum", 0.0)) / float(deltaj_cost_samples)
            if deltaj_cost_samples > 0 else float("nan")
        )
        service_rate_mean = (
            float(preventive_service_rate_mean_accum) / float(preventive_capacity_sample_count)
            if preventive_capacity_sample_count > 0 else float("nan")
        )
        direct_rate_mean = (
            float(preventive_direct_arrival_rate_mean_accum) / float(preventive_capacity_sample_count)
            if preventive_capacity_sample_count > 0 else float("nan")
        )
        capacity_remaining_mean = (
            float(preventive_capacity_remaining_mean_accum) / float(preventive_capacity_sample_count)
            if preventive_capacity_sample_count > 0 else float("nan")
        )

        calib_edges = [0.0, 0.2, 0.4, 0.6, 0.8, 1.0000001]
        calib_rows = [row for row in taskgen.rows() if (
            str(row.get("type", "")).strip().lower() == "deterring"
            and row.get("mode") not in (None, "", "none")
        )]
        calib_counts = [0] * 5
        calib_hits = [0] * 5
        eval_r2 = float(deterring_eval_radius_m) ** 2
        eval_window = float(deterring_eval_window_s)
        for row in calib_rows:
            p_val = float(row.get("p_event", float("nan")))
            if not np.isfinite(p_val):
                continue
            p_clamped = min(max(p_val, 0.0), 1.0)
            bin_idx = None
            for ii in range(5):
                if calib_edges[ii] <= p_clamped < calib_edges[ii + 1]:
                    bin_idx = ii
                    break
            if bin_idx is None:
                continue
            calib_counts[bin_idx] += 1
            tx = float(row.get("x", 0.0))
            ty = float(row.get("y", 0.0))
            tt = float(row.get("time", 0.0))
            hit = any(
                (evt_t >= tt)
                and (evt_t <= tt + eval_window)
                and (((evt_x - tx) ** 2 + (evt_y - ty) ** 2) <= eval_r2)
                for (evt_x, evt_y, evt_t) in truth_events
            )
            if hit:
                calib_hits[bin_idx] += 1

        def _safe_div(a, b):
            return (float(a) / float(b)) if float(b) > 0.0 else float("nan")

        phase4_metrics = {
            "model_deterring_gate_policy": str(model_deterring_gate_policy),
            "model_deterring_pass_sprt": int(diag_counts.get("model_deterring_pass_sprt", 0)),
            "model_deterring_rejected_sprt_pending": int(diag_counts.get("model_deterring_rejected_sprt_pending", 0)),
            "model_deterring_rejected_sprt_negative": int(diag_counts.get("model_deterring_rejected_sprt_negative", 0)),
            "model_deterring_pass_chance": int(diag_counts.get("model_deterring_pass_chance", 0)),
            "model_deterring_rejected_chance": int(diag_counts.get("model_deterring_rejected_chance", 0)),
            "model_deterring_pass_utility_ratio": int(diag_counts.get("model_deterring_pass_utility_ratio", 0)),
            "model_deterring_rejected_utility_ratio": int(diag_counts.get("model_deterring_rejected_utility_ratio", 0)),
            "model_deterring_pass_capacity": int(diag_counts.get("model_deterring_pass_capacity", 0)),
            "model_deterring_rejected_capacity": int(diag_counts.get("model_deterring_rejected_capacity", 0)),
            "model_deterring_llr_mean": float(llr_mean),
            "model_deterring_llr_max": float(llr_max),
            "model_deterring_p_event_mean": float(p_event_mean),
            "model_deterring_deltaJ_per_cost_mean": float(deltaj_per_cost_mean),
            "preventive_service_rate_per_robot_mean": float(service_rate_mean),
            "preventive_direct_arrival_rate_per_robot_mean": float(direct_rate_mean),
            "preventive_capacity_remaining_per_robot_mean": float(capacity_remaining_mean),
        }
        phase4_metrics.update({
            f"model_deterring_calibration_bin_{ii}_count": int(calib_counts[ii])
            for ii in range(5)
        })
        phase4_metrics.update({
            f"model_deterring_calibration_bin_{ii}_hits": int(calib_hits[ii])
            for ii in range(5)
        })
        phase4_metrics.update({
            f"model_deterring_calibration_bin_{ii}_hit_rate": _safe_div(calib_hits[ii], calib_counts[ii])
            for ii in range(5)
        })

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
            "robot_moving_fraction_by_robot": robot_moving_fraction_by_robot,
            "robot_longest_idle_s_by_robot": {rid: float(v) for rid, v in robot_idle_streak_max.items()},
            "robot_tail_idle_s_by_robot": {rid: float(v) for rid, v in robot_idle_streak.items()},
            "robot_task_utilization_mean": float(np.nanmean(list(robot_utilization_by_robot.values()))) if robot_utilization_by_robot else float("nan"),
            "robot_active_task_fraction_mean": float(np.nanmean(list(robot_utilization_by_robot.values()))) if robot_utilization_by_robot else float("nan"),
            "robot_idle_fraction_mean": float(np.nanmean(list(robot_idle_fraction_by_robot.values()))) if robot_idle_fraction_by_robot else float("nan"),
            "robot_moving_fraction_mean": float(np.nanmean(list(robot_moving_fraction_by_robot.values()))) if robot_moving_fraction_by_robot else float("nan"),
            "robot_moving_with_task_fraction_mean": float(np.nanmean(list(robot_moving_with_task_fraction_by_robot.values()))) if robot_moving_with_task_fraction_by_robot else float("nan"),
            "robot_longest_idle_s_max": float(max(robot_idle_streak_max.values())) if robot_idle_streak_max else float("nan"),
            "robot_tail_idle_s_max": float(max(robot_idle_streak.values())) if robot_idle_streak else float("nan"),
            "robots_zero_distance_count": int(sum(1 for rid in travel_distance_by_robot if travel_distance_by_robot[rid] <= 1e-6)),
            "stale_goal_clears": int(stale_goal_clears),
            "stale_task_evictions_count": int(stale_task_evictions_count),
            "stale_task_evictions_suppression": int(stale_task_evictions_suppression),
            "stale_task_evictions_age": int(stale_task_evictions_age),
            "stale_task_evictions_low_intensity": int(stale_task_evictions_low_intensity),
            "queue_depth_total_current": int(active_total),
            "queue_depth_patrolling_current": int(active_patrolling),
            "queue_depth_deterring_current": int(active_deterring),
            "queue_depth_model_deterring_current": int(active_model_deterring),
            "queue_depth_total_mean": _safe_div(queue_depth_total_sum, queue_depth_samples),
            "queue_depth_patrolling_mean": _safe_div(queue_depth_patrolling_sum, queue_depth_samples),
            "queue_depth_deterring_mean": _safe_div(queue_depth_deterring_sum, queue_depth_samples),
            "queue_depth_model_deterring_mean": _safe_div(queue_depth_model_deterring_sum, queue_depth_samples),
            "queue_depth_total_max": int(queue_depth_total_max),
            "queue_depth_patrolling_max": int(queue_depth_patrolling_max),
            "queue_depth_deterring_max": int(queue_depth_deterring_max),
            "queue_depth_model_deterring_max": int(queue_depth_model_deterring_max),
            "predicted_deltaJ_sum": float(predicted_deltaj_sum),
            "predicted_deltaJ_sum_direct_detection": float(predicted_deltaj_sum_direct),
            "predicted_deltaJ_sum_model_scored": float(predicted_deltaj_sum_model),
            "realized_suppression_sum": float(realized_suppression_sum),
            "realized_suppression_sum_direct_detection": float(realized_suppression_sum_direct),
            "realized_suppression_sum_model_scored": float(realized_suppression_sum_model),
            "yield_ratio_total": _safe_div(realized_suppression_sum, predicted_deltaj_sum),
            "yield_ratio_direct_detection": _safe_div(realized_suppression_sum_direct, predicted_deltaj_sum_direct),
            "yield_ratio_model_scored": _safe_div(realized_suppression_sum_model, predicted_deltaj_sum_model),
            "model_deterring_accepted": int(model_deterring_accepted),
            "model_deterring_rejected_budget": int(model_deterring_rejected_budget),
            "model_deterring_generated": int(diag_counts.get("model_deterring_generated", 0)),
            "model_deterring_candidates_total": int(diag_counts.get("model_deterring_candidates_total", 0)),
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
            "model_deterring_not_selected": int(diag_counts.get("model_deterring_not_selected", 0)),
            "model_deterring_rejected_budget_count_mode": int(model_deterring_rejected_budget_count_mode),
            "model_deterring_rejected_budget_utility_mode": int(model_deterring_rejected_budget_utility_mode),
            "model_deterring_budget_mode": str(model_deterring_budget_mode),
            "model_deterring_budget_spent_count_per_robot_hr": dict(budget_spent_count_by_robot),
            "model_deterring_budget_spent_utility_per_robot_hr": dict(budget_spent_utility_by_robot),
            "model_deterring_budget_spent_count_per_robot_hr_mean": float(np.mean(budget_count_vals)) if budget_count_vals else float("nan"),
            "model_deterring_budget_spent_count_per_robot_hr_max": float(np.max(budget_count_vals)) if budget_count_vals else float("nan"),
            "model_deterring_budget_spent_utility_per_robot_hr_mean": float(np.mean(budget_utility_vals)) if budget_utility_vals else float("nan"),
            "model_deterring_budget_spent_utility_per_robot_hr_max": float(np.max(budget_utility_vals)) if budget_utility_vals else float("nan"),
            "min_predicted_deltaJ_for_model_deterring": float(min_predicted_deltaJ_for_model_deterring),
            "planner_rejected_unassigned": int(planner_rejected_unassigned),
            "planner_rejected_task_cap": int(planner_rejected_task_cap),
            "planner_rejected_patrol_cap": int(planner_rejected_patrol_cap),
            "planner_rejected_model_det_cap": int(planner_rejected_model_det_cap),
            "planner_replaced_patrol": int(planner_replaced_patrol),
            "planner_replaced_low_utility_count": int(planner_replaced_low_utility_count),
            "assigned_task_value_mean": _safe_div(assigned_task_value_sum, assigned_task_value_count),
            "assigned_task_value_count": int(assigned_task_value_count),
            "assignment_method": str(assignment_method),
            "assigner_w_task_value": float(assigner_w_task_value),
            "assignment_solver_calls": int(assignment_solver_calls),
            "assignment_solver_runtime_ms": float(assignment_solver_runtime_ms_total / max(assignment_solver_calls, 1)),
            "assignment_solver_conflicts_resolved": int(assignment_solver_conflicts_resolved),
            "assignment_solver_unassigned": int(assignment_solver_unassigned),
            "assignment_solver_rounds_mean": float(assignment_solver_rounds_total / max(assignment_solver_calls, 1)),
            "assignment_solver_bid_updates": int(assignment_solver_bid_updates),
            "assignment_solver_message_passes": int(assignment_solver_message_passes),
            "assignment_solver_failures": int(assignment_solver_failures),
            "assignment_solver_feasible_edges": int(assignment_solver_feasible_edges),
            "assignment_solver_infeasible_edges": int(assignment_solver_infeasible_edges),
            "assignment_solver_feasible_edge_rate": (
                float(assignment_solver_feasible_edges)
                / float(max(1, assignment_solver_feasible_edges + assignment_solver_infeasible_edges))
            ),
            "truth_candidate_events": int(truth_candidate_events),
            "truth_accepted_events": int(truth_accepted_events),
            "truth_suppressed_events": int(truth_suppressed_events),
            "truth_suppression_rate": (float(truth_suppressed_events) / float(truth_candidate_events)) if truth_candidate_events > 0 else float("nan"),
            "truth_suppression_effect_mean": (float(suppression_effect_sum) / float(truth_candidate_events)) if truth_candidate_events > 0 else float("nan"),
            "truth_suppression_effect_sum": float(suppression_effect_sum),
            "truth_suppression_effect_by_mode": dict(suppression_effect_by_mode),
            "truth_suppression_effect_by_source": dict(suppression_effect_by_source),
            **deterring_quality_cache,
            **phase4_metrics,
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
            "robot_active_task_fraction_mean": float(np.nanmean(list(robot_utilization_by_robot.values()))) if robot_utilization_by_robot else float("nan"),
            "robot_idle_fraction_mean": float(np.nanmean(list(robot_idle_fraction_by_robot.values()))) if robot_idle_fraction_by_robot else float("nan"),
            "robot_moving_fraction_mean": float(np.nanmean(list(robot_moving_fraction_by_robot.values()))) if robot_moving_fraction_by_robot else float("nan"),
            "robot_moving_with_task_fraction_mean": float(np.nanmean(list(robot_moving_with_task_fraction_by_robot.values()))) if robot_moving_with_task_fraction_by_robot else float("nan"),
            "robot_longest_idle_s_max": float(max(robot_idle_streak_max.values())) if robot_idle_streak_max else float("nan"),
            "robot_tail_idle_s_max": float(max(robot_idle_streak.values())) if robot_idle_streak else float("nan"),
            "robots_zero_distance_count": int(sum(1 for rid in travel_distance_by_robot if travel_distance_by_robot[rid] <= 1e-6)),
            "stale_goal_clears": int(stale_goal_clears),
            "stale_task_evictions_count": int(stale_task_evictions_count),
            "stale_task_evictions_suppression": int(stale_task_evictions_suppression),
            "stale_task_evictions_age": int(stale_task_evictions_age),
            "stale_task_evictions_low_intensity": int(stale_task_evictions_low_intensity),
            "queue_depth_total_mean": _safe_div(queue_depth_total_sum, queue_depth_samples),
            "queue_depth_patrolling_mean": _safe_div(queue_depth_patrolling_sum, queue_depth_samples),
            "queue_depth_deterring_mean": _safe_div(queue_depth_deterring_sum, queue_depth_samples),
            "queue_depth_model_deterring_mean": _safe_div(queue_depth_model_deterring_sum, queue_depth_samples),
            "queue_depth_total_max": int(queue_depth_total_max),
            "queue_depth_patrolling_max": int(queue_depth_patrolling_max),
            "queue_depth_deterring_max": int(queue_depth_deterring_max),
            "queue_depth_model_deterring_max": int(queue_depth_model_deterring_max),
            "predicted_deltaJ_sum": float(predicted_deltaj_sum),
            "predicted_deltaJ_sum_direct_detection": float(predicted_deltaj_sum_direct),
            "predicted_deltaJ_sum_model_scored": float(predicted_deltaj_sum_model),
            "realized_suppression_sum": float(realized_suppression_sum),
            "realized_suppression_sum_direct_detection": float(realized_suppression_sum_direct),
            "realized_suppression_sum_model_scored": float(realized_suppression_sum_model),
            "yield_ratio_total": _safe_div(realized_suppression_sum, predicted_deltaj_sum),
            "yield_ratio_direct_detection": _safe_div(realized_suppression_sum_direct, predicted_deltaj_sum_direct),
            "yield_ratio_model_scored": _safe_div(realized_suppression_sum_model, predicted_deltaj_sum_model),
            "model_deterring_accepted": int(model_deterring_accepted),
            "model_deterring_rejected_budget": int(model_deterring_rejected_budget),
            "model_deterring_generated": int(diag_counts.get("model_deterring_generated", 0)),
            "model_deterring_candidates_total": int(diag_counts.get("model_deterring_candidates_total", 0)),
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
            "model_deterring_not_selected": int(diag_counts.get("model_deterring_not_selected", 0)),
            "model_deterring_rejected_budget_count_mode": int(model_deterring_rejected_budget_count_mode),
            "model_deterring_rejected_budget_utility_mode": int(model_deterring_rejected_budget_utility_mode),
            "model_deterring_budget_mode": str(model_deterring_budget_mode),
            "model_deterring_budget_spent_count_per_robot_hr_mean": float(np.mean(budget_count_vals)) if budget_count_vals else float("nan"),
            "model_deterring_budget_spent_count_per_robot_hr_max": float(np.max(budget_count_vals)) if budget_count_vals else float("nan"),
            "model_deterring_budget_spent_utility_per_robot_hr_mean": float(np.mean(budget_utility_vals)) if budget_utility_vals else float("nan"),
            "model_deterring_budget_spent_utility_per_robot_hr_max": float(np.max(budget_utility_vals)) if budget_utility_vals else float("nan"),
            "min_predicted_deltaJ_for_model_deterring": float(min_predicted_deltaJ_for_model_deterring),
            "planner_rejected_unassigned": int(planner_rejected_unassigned),
            "planner_rejected_task_cap": int(planner_rejected_task_cap),
            "planner_rejected_patrol_cap": int(planner_rejected_patrol_cap),
            "planner_rejected_model_det_cap": int(planner_rejected_model_det_cap),
            "planner_replaced_patrol": int(planner_replaced_patrol),
            "planner_replaced_low_utility_count": int(planner_replaced_low_utility_count),
            "assigned_task_value_mean": _safe_div(assigned_task_value_sum, assigned_task_value_count),
            "assigned_task_value_count": int(assigned_task_value_count),
            "assignment_method": str(assignment_method),
            "assigner_w_task_value": float(assigner_w_task_value),
            "assignment_solver_calls": int(assignment_solver_calls),
            "assignment_solver_runtime_ms": float(assignment_solver_runtime_ms_total / max(assignment_solver_calls, 1)),
            "assignment_solver_conflicts_resolved": int(assignment_solver_conflicts_resolved),
            "assignment_solver_unassigned": int(assignment_solver_unassigned),
            "assignment_solver_rounds_mean": float(assignment_solver_rounds_total / max(assignment_solver_calls, 1)),
            "assignment_solver_bid_updates": int(assignment_solver_bid_updates),
            "assignment_solver_message_passes": int(assignment_solver_message_passes),
            "assignment_solver_failures": int(assignment_solver_failures),
            "assignment_solver_feasible_edges": int(assignment_solver_feasible_edges),
            "assignment_solver_infeasible_edges": int(assignment_solver_infeasible_edges),
            "assignment_solver_feasible_edge_rate": (
                float(assignment_solver_feasible_edges)
                / float(max(1, assignment_solver_feasible_edges + assignment_solver_infeasible_edges))
            ),
            "truth_candidate_events": int(truth_candidate_events),
            "truth_accepted_events": int(truth_accepted_events),
            "truth_suppressed_events": int(truth_suppressed_events),
            "truth_suppression_rate": (float(truth_suppressed_events) / float(truth_candidate_events)) if truth_candidate_events > 0 else float("nan"),
            "truth_suppression_effect_mean": (float(suppression_effect_sum) / float(truth_candidate_events)) if truth_candidate_events > 0 else float("nan"),
            "truth_suppression_effect_sum": float(suppression_effect_sum),
            **deterring_quality_cache,
            **phase4_metrics,
            "forecast_recall_at_k": float(np.mean(forecast_recall_vals)) if forecast_recall_vals else float("nan"),
            "forecast_precision_at_k": float(np.mean(forecast_precision_vals)) if forecast_precision_vals else float("nan"),
            "forecast_lead_time_s": float(np.mean(forecast_lead_times)) if forecast_lead_times else float("nan"),
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
            "global_hotspots": debug_global_hotspots,
            "field_xs": debug_field_xs,
            "field_ys": debug_field_ys,
            "field_lam": debug_field_lam,
            "field_mu": debug_field_mu,
            "local_hotspot_score_stats": list(debug_last_local_hotspot_score_stats) if bool(export_task_debug) else [],
            "local_hotspots_raw": list(debug_last_local_hotspots_raw) if bool(export_task_debug) else [],
            "local_hotspots_score_filtered": list(debug_last_local_hotspots_score_filtered) if bool(export_task_debug) else [],
            "local_hotspots_spaced": list(debug_last_local_hotspots_spaced) if bool(export_task_debug) else [],
            "raw_patrol_candidates": list(debug_last_raw_patrol_candidates) if bool(export_task_debug) else [],
            "selected_patrol_tasks": list(debug_last_selected_patrol_tasks) if bool(export_task_debug) else [],
            "tasks_active": list(active_tasks),
            "tasks_done": list(completed_tasks)
        }

        t += dt

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
            f"msgs={total_boundary_msgs} "
            f"bytes={total_boundary_bytes}"
        )


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
            m = dict(last["metrics"])
            m["seed"] = int(seed)
            m["run_idx"] = int(i)
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
        "intervention_msg_dropped_debounce": _safe_stats("intervention_msg_dropped_debounce"),
        "intervention_msg_dropped_low_weight": _safe_stats("intervention_msg_dropped_low_weight"),
        "forecast_recall_at_k": _safe_stats("forecast_recall_at_k"),
        "forecast_precision_at_k": _safe_stats("forecast_precision_at_k"),
        "forecast_lead_time_s": _safe_stats("forecast_lead_time_s"),
        "forecast_hotspot_hit_rate": _safe_stats("forecast_hotspot_hit_rate"),
        "predicted_deltaJ_sum": _safe_stats("predicted_deltaJ_sum"),
        "predicted_deltaJ_sum_direct_detection": _safe_stats("predicted_deltaJ_sum_direct_detection"),
        "predicted_deltaJ_sum_model_scored": _safe_stats("predicted_deltaJ_sum_model_scored"),
        "realized_suppression_sum": _safe_stats("realized_suppression_sum"),
        "realized_suppression_sum_direct_detection": _safe_stats("realized_suppression_sum_direct_detection"),
        "realized_suppression_sum_model_scored": _safe_stats("realized_suppression_sum_model_scored"),
        "yield_ratio_total": _safe_stats("yield_ratio_total"),
        "yield_ratio_direct_detection": _safe_stats("yield_ratio_direct_detection"),
        "yield_ratio_model_scored": _safe_stats("yield_ratio_model_scored"),
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
        "model_deterring_pass_sprt": _safe_stats("model_deterring_pass_sprt"),
        "model_deterring_rejected_sprt_pending": _safe_stats("model_deterring_rejected_sprt_pending"),
        "model_deterring_rejected_sprt_negative": _safe_stats("model_deterring_rejected_sprt_negative"),
        "model_deterring_pass_chance": _safe_stats("model_deterring_pass_chance"),
        "model_deterring_rejected_chance": _safe_stats("model_deterring_rejected_chance"),
        "model_deterring_pass_utility_ratio": _safe_stats("model_deterring_pass_utility_ratio"),
        "model_deterring_rejected_utility_ratio": _safe_stats("model_deterring_rejected_utility_ratio"),
        "model_deterring_pass_capacity": _safe_stats("model_deterring_pass_capacity"),
        "model_deterring_rejected_capacity": _safe_stats("model_deterring_rejected_capacity"),
        "model_deterring_llr_mean": _safe_stats("model_deterring_llr_mean"),
        "model_deterring_llr_max": _safe_stats("model_deterring_llr_max"),
        "model_deterring_p_event_mean": _safe_stats("model_deterring_p_event_mean"),
        "model_deterring_deltaJ_per_cost_mean": _safe_stats("model_deterring_deltaJ_per_cost_mean"),
        "preventive_service_rate_per_robot_mean": _safe_stats("preventive_service_rate_per_robot_mean"),
        "preventive_direct_arrival_rate_per_robot_mean": _safe_stats("preventive_direct_arrival_rate_per_robot_mean"),
        "preventive_capacity_remaining_per_robot_mean": _safe_stats("preventive_capacity_remaining_per_robot_mean"),
        "model_deterring_budget_spent_count_per_robot_hr_mean": _safe_stats("model_deterring_budget_spent_count_per_robot_hr_mean"),
        "model_deterring_budget_spent_count_per_robot_hr_max": _safe_stats("model_deterring_budget_spent_count_per_robot_hr_max"),
        "model_deterring_budget_spent_utility_per_robot_hr_mean": _safe_stats("model_deterring_budget_spent_utility_per_robot_hr_mean"),
        "model_deterring_budget_spent_utility_per_robot_hr_max": _safe_stats("model_deterring_budget_spent_utility_per_robot_hr_max"),
        "min_predicted_deltaJ_for_model_deterring": _safe_stats("min_predicted_deltaJ_for_model_deterring"),
        "model_deterring_rejected_risk": _safe_stats("model_deterring_rejected_risk"),
        "model_deterring_rejected_support": _safe_stats("model_deterring_rejected_support"),
        "model_deterring_rejected_persistence": _safe_stats("model_deterring_rejected_persistence"),
        "model_deterring_rejected_repeat_no_new_support": _safe_stats("model_deterring_rejected_repeat_no_new_support"),
        "model_deterring_rejected_eta": _safe_stats("model_deterring_rejected_eta"),
        "model_deterring_rejected_busy": _safe_stats("model_deterring_rejected_busy"),
        "model_deterring_rejected_margin": _safe_stats("model_deterring_rejected_margin"),
        "planner_rejected_unassigned": _safe_stats("planner_rejected_unassigned"),
        "planner_rejected_task_cap": _safe_stats("planner_rejected_task_cap"),
        "planner_rejected_patrol_cap": _safe_stats("planner_rejected_patrol_cap"),
        "planner_rejected_model_det_cap": _safe_stats("planner_rejected_model_det_cap"),
        "planner_replaced_patrol": _safe_stats("planner_replaced_patrol"),
        "planner_replaced_low_utility_count": _safe_stats("planner_replaced_low_utility_count"),
        "assigned_task_value_mean": _safe_stats("assigned_task_value_mean"),
        "assigned_task_value_count": _safe_stats("assigned_task_value_count"),
        "assignment_solver_calls": _safe_stats("assignment_solver_calls"),
        "assignment_solver_runtime_ms": _safe_stats("assignment_solver_runtime_ms"),
        "assignment_solver_conflicts_resolved": _safe_stats("assignment_solver_conflicts_resolved"),
        "assignment_solver_unassigned": _safe_stats("assignment_solver_unassigned"),
        "assignment_solver_rounds_mean": _safe_stats("assignment_solver_rounds_mean"),
        "assignment_solver_bid_updates": _safe_stats("assignment_solver_bid_updates"),
        "assignment_solver_message_passes": _safe_stats("assignment_solver_message_passes"),
        "assignment_solver_failures": _safe_stats("assignment_solver_failures"),
        "assignment_solver_feasible_edges": _safe_stats("assignment_solver_feasible_edges"),
        "assignment_solver_infeasible_edges": _safe_stats("assignment_solver_infeasible_edges"),
        "assignment_solver_feasible_edge_rate": _safe_stats("assignment_solver_feasible_edge_rate"),
        "truth_candidate_events": _safe_stats("truth_candidate_events"),
        "truth_accepted_events": _safe_stats("truth_accepted_events"),
        "truth_suppressed_events": _safe_stats("truth_suppressed_events"),
        "truth_suppression_rate": _safe_stats("truth_suppression_rate"),
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
        "robot_active_task_fraction_mean": _safe_stats("robot_active_task_fraction_mean"),
        "robot_idle_fraction_mean": _safe_stats("robot_idle_fraction_mean"),
        "robot_moving_fraction_mean": _safe_stats("robot_moving_fraction_mean"),
        "robot_moving_with_task_fraction_mean": _safe_stats("robot_moving_with_task_fraction_mean"),
        "robot_longest_idle_s_max": _safe_stats("robot_longest_idle_s_max"),
        "robot_tail_idle_s_max": _safe_stats("robot_tail_idle_s_max"),
        "robots_zero_distance_count": _safe_stats("robots_zero_distance_count"),
        "stale_goal_clears": _safe_stats("stale_goal_clears"),
        "stale_task_evictions_count": _safe_stats("stale_task_evictions_count"),
        "stale_task_evictions_suppression": _safe_stats("stale_task_evictions_suppression"),
        "stale_task_evictions_age": _safe_stats("stale_task_evictions_age"),
        "stale_task_evictions_low_intensity": _safe_stats("stale_task_evictions_low_intensity"),
        "queue_depth_total_mean": _safe_stats("queue_depth_total_mean"),
        "queue_depth_patrolling_mean": _safe_stats("queue_depth_patrolling_mean"),
        "queue_depth_deterring_mean": _safe_stats("queue_depth_deterring_mean"),
        "queue_depth_model_deterring_mean": _safe_stats("queue_depth_model_deterring_mean"),
        "queue_depth_total_max": _safe_stats("queue_depth_total_max"),
        "queue_depth_patrolling_max": _safe_stats("queue_depth_patrolling_max"),
        "queue_depth_deterring_max": _safe_stats("queue_depth_deterring_max"),
        "queue_depth_model_deterring_max": _safe_stats("queue_depth_model_deterring_max"),
    }
    for ii in range(5):
        summary[f"model_deterring_calibration_bin_{ii}_count"] = _safe_stats(f"model_deterring_calibration_bin_{ii}_count")
        summary[f"model_deterring_calibration_bin_{ii}_hits"] = _safe_stats(f"model_deterring_calibration_bin_{ii}_hits")
        summary[f"model_deterring_calibration_bin_{ii}_hit_rate"] = _safe_stats(f"model_deterring_calibration_bin_{ii}_hit_rate")

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

    return {
        "num_runs": len(run_metrics),
        "runs": run_metrics,
        "summary": summary,
        "time_summary": time_summary,
    }


def run_baseline_suite(
    num_runs=10,
    seed_start=123,
    report_each_run=True,
    csv_path=None,
    progress_cb=None,
    collect_time_metrics=True,
    time_metrics_period_s=900.0,
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

    all_results = {}
    rows = []
    time_rows = []
    baseline_names = list(baseline_cfgs.keys())
    total_runs_all = int(num_runs) * len(baseline_names)
    runs_done_all = 0

    for bidx, name in enumerate(baseline_names, start=1):
        cfg = baseline_cfgs[name]
        if report_each_run:
            print(f"[baseline] {name}")
        run_kwargs = dict(sim_kwargs)
        run_kwargs.update(cfg)
        def _baseline_progress(run_idx, run_total, seed, metrics):
            nonlocal runs_done_all
            runs_done_all = (bidx - 1) * int(num_runs) + int(run_idx)
            pct = 100.0 * runs_done_all / max(total_runs_all, 1)
            bar_len = 30
            fill = int(round(bar_len * pct / 100.0))
            bar = "#" * fill + "-" * (bar_len - fill)
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
        row = {"baseline": name, "num_runs": int(result.get("num_runs", 0))}
        for metric_name, stats in summary.items():
            row[f"{metric_name}_mean"] = float(stats.get("mean", np.nan))
            row[f"{metric_name}_var"] = float(stats.get("var", np.nan))
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
