import random
import numpy as np
from typing import Dict, List
import pandas as pd
import math, numpy as np
import os
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
from TaskGenerator import TaskGenerator, TaskAssigner

class EventBus:
    def __init__(self, robots: Dict[str, Robot], bytes_per_boundary_msg: int = 64, bytes_per_intervention_msg: int = 72):
        self.robots = robots
        self.bytes_per_boundary_msg = int(bytes_per_boundary_msg)
        self.bytes_per_intervention_msg = int(bytes_per_intervention_msg)
        self.boundary_msg_count = 0
        self.intervention_msg_count = 0
        self.boundary_bytes = 0
        self.intervention_bytes = 0
    
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
    
    def send_intervention_events(self, events: List[Dict], source_id: str):
        for ev in events:
            rid = ev['target_robot']
            if rid in self.robots and rid != source_id:
                self.intervention_msg_count += 1
                self.intervention_bytes += self.bytes_per_intervention_msg
                self.robots[rid].ingest_intervention_event(
                    x=ev['x'], y=ev['y'], t=ev['t'],
                    weight=ev.get('weight', 1.0), sigma=ev.get('sigma'), omega_inhib=ev.get('omega_inhib')
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
    # Simulation mode selector
    simulation_mode="proposed",
    # Baseline toggles
    enable_patrolling=None,
    enable_intervention_feedback=None,
    include_fallback_patrol=None,
    # Deterring action modes (benefit/cost params)
    deterring_modes=None,
    # Ground-truth event process (event-driven)
    use_ground_truth=True,
    mu_true=1e-6,            # base rate per m^2 per s (scaled by w(x))
    alpha_true=0.3,          # offspring mean per event
    omega_true=600.0,        # temporal decay for offspring + suppression
    sigma_true=12.0,         # spatial spread for offspring + suppression
    beta_true=0.25,          # suppression strength
    detect_range_m=30.0,     # detections only within range of robot
    event_viz_window_s=20.0, # seconds of events to keep in plot
    telemetry_dir="telemetry_live",
    telemetry_clear_on_start=True,
    telemetry_prompt_save=True,
    # Metrics
    response_match_radius_m=25.0,
    ugv_energy_per_m=1.0,
    uav_energy_per_m=1.0,
    bytes_per_boundary_msg=64,
    bytes_per_intervention_msg=72,
    report_metrics_end=True,
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
    row_block_gap_m=12.0
):
    rng = np.random.default_rng(seed)
    boundary = [(0,0),(W,0),(W,H),(0,H)]

    mode_key = str(simulation_mode).lower().strip()
    mode_defaults = {
        "reactive": {
            "enable_patrolling": False,
            "enable_intervention_feedback": False,
            "include_fallback_patrol": False,
        },
        "prediction_only": {
            "enable_patrolling": True,
            "enable_intervention_feedback": False,
            "include_fallback_patrol": True,
        },
        "proposed": {
            "enable_patrolling": True,
            "enable_intervention_feedback": True,
            "include_fallback_patrol": True,
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
    recent_truth = deque(maxlen=5000)      # (x,y,t) for plotting
    recent_detections = deque(maxlen=5000) # (x,y,t) for plotting
    truth_queue = []      # scheduled offspring events (x,y,t)
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

    def _suppression_factor(x, y, t_now):
        if not recent_deterrences:
            return 1.0
        s = 0.0
        for (zx, zy, tz) in recent_deterrences:
            dt = t_now - tz
            if dt < 0:
                continue
            k = math.exp(-0.5 * ((x - zx)**2 + (y - zy)**2) / max(sigma_true**2, 1e-9))
            s += beta_true * k * math.exp(-dt / max(omega_true, 1e-9))
        return math.exp(-s)

    def _process_truth_event(x, y, t_now):
        nonlocal value_weighted_exposure
        truth_events.append((x, y, t_now))
        recent_truth.append((x, y, t_now))
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
            taskgen.on_detection(owner, x, y, t_now)
            pending_event_onsets.append({"x": float(x), "y": float(y), "t": float(t_now), "responded": False})
            recent_detections.append((x, y, t_now))
            if mon is not None and getattr(mon, 'enabled', False):
                mon.message(t_now, kind='detection', source=owner, target=owner,
                            data={'x': x, 'y': y})

    def _spawn_offspring(x, y, t_now):
        n = rng.poisson(alpha_true)
        for _ in range(int(n)):
            dt_off = rng.exponential(omega_true)
            xo = float(np.clip(x + rng.normal(0.0, sigma_true), 0.0, W))
            yo = float(np.clip(y + rng.normal(0.0, sigma_true), 0.0, H))
            truth_queue.append((xo, yo, t_now + dt_off))

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
        },
    )
    next_tid = 1
    active_tasks = []     # list of dicts: {id, type, x,y,time,origin,assigned_primary,assigned_secondary,state,started_hold}
    completed_tasks = []  # same schema + state='done'
    recent_deterrences = deque(maxlen=200)  # (x,y,t)

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
        nonlocal next_tid
        # Add patrolling (periodic) at cadence / OR immediate deterring already enqueued by on_detection
        if not patrolling_only:
            pass  # (deterring tasks are added via on_detection below)
        # Produce patrolling on cadence when enabled.
        if enable_patrolling:
            taskgen.periodic_patrolling(robots=robots, now_t=now_t,
                                        hotspot_top_k=5, include_fallback_patrol=include_fallback_patrol,
                                        deterring_window_s=0.0,
                                        profiles=profiles,
                                        spinup_by_type={"UAV": 8.0, "UGV": 0.0},
                                        weight_fn=value_weight,
                                        deterring_modes=deterring_modes)
        # Figure out the delta since last persist
        # For simplicity, read the tail: anything not yet in active/completed by (x,y,time,type)
        seen_keys = {(t['type'], round(t['x'],2), round(t['y'],2), round(t['time'],0)) for t in active_tasks}
        seen_keys |= {(t['type'], round(t['x'],2), round(t['y'],2), round(t['time'],0)) for t in completed_tasks}
        for t in taskgen.rows()[-200:]:  # recent window
            if (not np.isfinite(t.get("x", float("nan")))) or (not np.isfinite(t.get("y", float("nan")))):
                continue
            key = (t['type'], round(t['x'],2), round(t['y'],2), round(t['time'],0))
            if key in seen_keys: 
                continue
            res = assigner.assign_task(t)
            assigned_primary   = res and res["primary"]
            assigned_secondary = res and res["secondary"]
            active_tasks.append({
                "id": next_tid, **t,
                "assigned_primary": assigned_primary,
                "assigned_secondary": assigned_secondary,
                "state": "active",
                "started_hold": None     # for deterring completion
            })

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
    t = 0.0
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

    while t <= T_end:
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
                    if rng.random() <= _suppression_factor(x, y, t):
                        _process_truth_event(x, y, t)
                        _spawn_offspring(x, y, t)

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
                    if rng.random() <= _suppression_factor(x, y, te):
                        _process_truth_event(x, y, te)
                        _spawn_offspring(x, y, te)
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
            # Drop tasks that are close to recent deterrences
            if recent_deterrences:
                active_tasks[:] = [
                    tr for tr in active_tasks
                    if not any(
                        (t0 >= t - deterring_suppress_window_s) and
                        ((tr["x"]-dx)**2 + (tr["y"]-dy)**2 <= deterring_suppress_radius_m**2)
                        for (dx, dy, t0) in recent_deterrences
                    )
                ]
            # Prune tasks that are stale or no longer supported by intensity
            active_tasks[:] = [
                tr for tr in active_tasks
                if (t - tr.get("time", t) <= task_max_age_s) and
                   (_task_intensity_score(tr) >= task_refresh_min_score)
            ]
            _spawn_and_assign_new_tasks(now_t=t, patrolling_only=False)
            last_replan = t

        # 4) Move robots toward goals; complete tasks on arrival rules
        for r in robots_def:
            rid = r['id']
            # If holding at a deterring site, keep holding
            if loiter_until[rid] > t:
                pass
            else:
                # If idle and there exists an active task assigned to this robot, pick nearest one
                if goal[rid] is None:
                    candidates = [tr for tr in active_tasks if tr["assigned_primary"] == rid and tr["state"]=="active"]
                    if candidates:
                        # pick nearest
                        px,py = pose[rid]
                        tid, gx, gy = min(((tr["id"], tr["x"], tr["y"]) for tr in candidates),
                                          key=lambda z: math.hypot(z[1]-px, z[2]-py))
                        goal[rid] = (gx, gy)
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
                                completed_tasks.append(tr)
                                completed_count_by_type["deterring"] += 1
                                completed_task_scores.append(float(tr.get("score", 0.0)))
                                recent_deterrences.append((tr["x"], tr["y"], t))
                                mode = tr.get("mode")
                                params = deterring_modes.get(mode, {}) if mode else {}
                                w = float(params.get("beta", 1.0))
                                omega_u = float(params.get("omega", robots[rid].m.omega_inhib))
                                sigma_u = float(params.get("sigma", robots[rid].m.sigma))
                                if enable_intervention_feedback:
                                    robots[rid].ingest_intervention_event(tr["x"], tr["y"], t, weight=w,
                                                                         sigma=sigma_u, omega_inhib=omega_u)
                                    b = robots[rid].intervention_boundary_events(tr["x"], tr["y"], t, weight=w)
                                    bus.send_intervention_events(b, source_id=rid)
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
        }
        final_metrics = {
            "value_weighted_exposure": float(value_weighted_exposure),
            "mean_response_time_s": float(np.mean(response_times)) if response_times else float("nan"),
            "completed_tasks_total": int(total_completed),
            "travel_distance_total": float(total_distance),
            "boundary_message_count": int(total_boundary_msgs),
            "boundary_bytes_sent": int(total_boundary_bytes),
        }
        yield {
            "t": t,
            "W": W, "H": H, "boundary": boundary,
            "cells": list(cells),
            "poses": {rid: tuple(pose[rid]) for rid in pose},
            "robot_states": {
                rid: ("holding" if loiter_until[rid] > t else ("moving" if goal[rid] is not None else "idle"))
                for rid in pose
            },
            "robot_goals": {rid: (None if goal[rid] is None else tuple(goal[rid])) for rid in goal},
            "profiles": profiles,
            "truth_pts": truth_pts,
            "det_pts": det_pts,
            "metrics": metrics,
            "metrics_compact": final_metrics,
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
        print(
            "[run metrics] "
            f"Jexp={float(value_weighted_exposure):.3f} "
            f"resp_s={mrt:.3f} "
            f"tasks={total_completed} "
            f"dist={total_distance:.3f} "
            f"msgs={total_boundary_msgs} "
            f"bytes={total_boundary_bytes}"
        )


def run_metrics_experiments(num_runs=10, seed_start=123, report_each_run=True, progress_cb=None, **sim_kwargs):
    """
    Run multiple randomized simulations and report mean/variance metrics.
    """
    run_metrics = []
    for i in range(int(num_runs)):
        seed = int(seed_start) + i
        frames = run_simulation_frames_persistent(seed=seed, **sim_kwargs)
        last = None
        for snap in frames:
            last = snap
        if last is not None and "metrics" in last:
            m = last["metrics"]
            run_metrics.append(m)
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
        return {"num_runs": 0, "runs": [], "summary": {}}

    def _arr(key):
        return np.array([m.get(key, np.nan) for m in run_metrics], dtype=float)

    summary = {
        "value_weighted_exposure": {
            "mean": float(np.nanmean(_arr("value_weighted_exposure"))),
            "var": float(np.nanvar(_arr("value_weighted_exposure"))),
        },
        "mean_response_time_s": {
            "mean": float(np.nanmean(_arr("mean_response_time_s"))),
            "var": float(np.nanvar(_arr("mean_response_time_s"))),
        },
        "tasks_per_unit_distance": {
            "mean": float(np.nanmean(_arr("tasks_per_unit_distance"))),
            "var": float(np.nanvar(_arr("tasks_per_unit_distance"))),
        },
        "exposure_per_completed_task": {
            "mean": float(np.nanmean(_arr("exposure_per_completed_task"))),
            "var": float(np.nanvar(_arr("exposure_per_completed_task"))),
        },
        "boundary_message_count": {
            "mean": float(np.nanmean(_arr("boundary_message_count"))),
            "var": float(np.nanvar(_arr("boundary_message_count"))),
        },
        "boundary_bytes_sent": {
            "mean": float(np.nanmean(_arr("boundary_bytes_sent"))),
            "var": float(np.nanvar(_arr("boundary_bytes_sent"))),
        },
    }
    return {"num_runs": len(run_metrics), "runs": run_metrics, "summary": summary}


def run_baseline_suite(num_runs=10, seed_start=123, report_each_run=True, csv_path=None, progress_cb=None, **sim_kwargs):
    """
    Run and compare baseline families:
    - reactive: detections only, no predictive patrol, no intervention feedback
    - prediction_only: predictive patrol enabled, no intervention feedback
    - proposed: predictive patrol + intervention feedback
    Returns per-baseline full results plus a flattened comparison table.
    """
    baseline_cfgs = {
        "reactive": {
            "enable_patrolling": False,
            "enable_intervention_feedback": False,
            "include_fallback_patrol": False,
        },
        "prediction_only": {
            "enable_patrolling": True,
            "enable_intervention_feedback": False,
            "include_fallback_patrol": True,
        },
        "proposed": {
            "enable_patrolling": True,
            "enable_intervention_feedback": True,
            "include_fallback_patrol": True,
        },
    }

    all_results = {}
    rows = []
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
            **run_kwargs,
        )
        all_results[name] = result
        summary = result.get("summary", {})
        row = {"baseline": name, "num_runs": int(result.get("num_runs", 0))}
        for metric_name, stats in summary.items():
            row[f"{metric_name}_mean"] = float(stats.get("mean", np.nan))
            row[f"{metric_name}_var"] = float(stats.get("var", np.nan))
        rows.append(row)

    comparison_df = pd.DataFrame(rows)
    if csv_path:
        csv_dir = os.path.dirname(os.path.abspath(csv_path))
        if csv_dir:
            os.makedirs(csv_dir, exist_ok=True)
        comparison_df.to_csv(csv_path, index=False)
        if report_each_run:
            print(f"[baseline] comparison csv written: {csv_path}")

    return {"baselines": all_results, "comparison": comparison_df}


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
