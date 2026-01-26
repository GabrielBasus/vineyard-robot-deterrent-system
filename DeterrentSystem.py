import random
import numpy as np
from typing import Dict, List
import pandas as pd
import math, numpy as np
import matplotlib.pyplot as plt
from matplotlib.animation import FuncAnimation
from matplotlib.patches import Polygon as MplPolygon
from collections import deque

try:
    from telemetry_sim import TelemetrySim
    mon: 'TelemetrySim|None' = TelemetrySim(enabled=True)
except Exception:
    mon = None  # telemetry disabled if import fails

from ZonePartitioner import ZonePartitioner, power_cells, build_neighbors, point_in_polygon, health_to_weight
from SESTPP import OnlineSESTPP
from Robot import Robot, RobotProfile
from TaskGenerator import TaskGenerator, TaskAssigner

class EventBus:
    def __init__(self, robots: Dict[str, Robot]):
        self.robots = robots
    
    def send_boundary_events(self, events: List[Dict], source_id: str):
        for ev in events:
            rid = ev['target_robot']
            if rid in self.robots and rid != source_id:
                self.robots[rid].ingest_boundary_event(
                    x=ev['x'], y=ev['y'], t=ev['t'],
                    weight=ev.get('weight', 0.35), sigma=ev.get('sigma'), omega=ev.get('omega')
                )
    
    def send_intervention_events(self, events: List[Dict], source_id: str):
        for ev in events:
            rid = ev['target_robot']
            if rid in self.robots and rid != source_id:
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
    W=500.0, H=400.0, seed=123, dt=1.0, T_end=240.0, fps=10,
    # Fleet
    Nrobots=None, uav_fraction=0.4,
    # Zones (health → weight), anchored to **initial positions**
    mode="direct", scale=15000.0, gamma=1.5,
    health_threshold=0.25,   # trigger-only partitioning (optional)
    # SESTPP
    NX=120, NY=96, sigma=16.0, omega=700.0, mu_base=1e-4, bg_ema=3e-4,
    # Detections near robots
    detect_rate_per_robot=0.08, detect_sigma_m=10.0,

    bird_stay_mean_s=30.0,       # how long a bird lingers near a robot (exp. mean)
    bird_detection_prob=0.25,    # per-step chance to emit a detection while present
    per_robot_cooldown_s=3.0,    # minimum time between detections for each robot
    max_detections_per_step=2,   # safety cap per step per robot
    
    # Tasks / motion
    task_replan_period_s=5.0, arrival_radius_m=3.0, hold_time_s=20.0
):
    rng = np.random.default_rng(seed)
    boundary = [(0,0),(W,0),(W,H),(0,H)]

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

    # --- Task system: persistent tasks (active + completed) ---
    taskgen  = TaskGenerator(merge_radius_m=max(8.0, 0.5*sigma))
    assigner = TaskAssigner(robots_state=robots, profiles=profiles, params={"uav_spinup_s": 8.0})
    next_tid = 1
    active_tasks = []     # list of dicts: {id, type, x,y,time,origin,assigned_primary,assigned_secondary,state,started_hold}
    completed_tasks = []  # same schema + state='done'

    # --- Telemetry: initial zones and poses ---
    if mon is not None and getattr(mon, 'enabled', False):
        for i, r in enumerate(robots_def):
            rid = r['id']
            if i < len(cells):
                mon.set_zone(rid, cells[i], t=0.0)
            x0, y0 = pose[rid]
            mon.pose(t=0.0, rid=rid, x=x0, y=y0)


    def _spawn_and_assign_new_tasks(now_t, patrolling_only=False):
        """Pull new tasks from TaskGenerator buffer and make them persistent until completion."""
        nonlocal next_tid
        # Add patrolling (periodic) at cadence / OR immediate deterring already enqueued by on_detection
        if not patrolling_only:
            pass  # (deterring tasks are added via on_detection below)
        # Always produce patrolling on cadence:
        taskgen.periodic_patrolling(robots=robots, now_t=now_t,
                                    hotspot_top_k=5, include_fallback_patrol=True,
                                    deterring_window_s=0.0)
        # Figure out the delta since last persist
        # For simplicity, read the tail: anything not yet in active/completed by (x,y,time,type)
        seen_keys = {(t['type'], round(t['x'],2), round(t['y'],2), round(t['time'],0)) for t in active_tasks}
        seen_keys |= {(t['type'], round(t['x'],2), round(t['y'],2), round(t['time'],0)) for t in completed_tasks}
        for t in taskgen.rows()[-200:]:  # recent window
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
            next_tid += 1

    # Motion helpers
    def _step_to(rid, tgt, dt):
        x,y = pose[rid]; tx,ty = tgt
        dx,dy = tx-x, ty-y; d = math.hypot(dx,dy)
        if d < 1e-6: 
            return
        v = profiles[rid].speed_mps
        step = v*dt
        pose[rid] = (tx,ty) if step >= d else (x + dx*(step/d), y + dy*(step/d))

    # Sim clocks / cadence
    t = 0.0
    last_replan = -1e9

    while t <= T_end:
        # 1) Optional: trigger-only repartition on health threshold
        if any(profiles[rid].health <= health_threshold for rid in profiles):
            partitioner.recompute(force=True)
            cells = partitioner.cells_for_ids()
            id_to_cell = {rid: cells[i] for i, rid in enumerate(partitioner.ids)}
            for r in robots_def:
                rid = r['id']
                robots[rid].update_zone(id_to_cell.get(rid, []))   # UAVs: []
                robots[rid].update_neighbors(partitioner.neighbors_for_id(rid))
                if mon is not None and getattr(mon, 'enabled', False):
                    if i < len(cells):
                        mon.set_zone(rid, cells[i], t=t)


        # 2) Detections near robots (immediate deterring tasks added)
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
                            EventBus(robots).send_boundary_events(b, source_id=owner)
                            taskgen.on_detection(owner, x, y, t)
                            if mon is not None and getattr(mon, 'enabled', False):
                                mon.message(t, kind='detection', source=owner, target=owner,
                                            data={'x': x, 'y': y})

                            last_detection_time[rid] = t
                            generated += 1

        # 3) Periodic patrolling + making tasks persistent (and assigned)
        if (t - last_replan) >= task_replan_period_s:
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
            if goal[rid] is not None and math.hypot(pose[rid][0]-goal[rid][0], pose[rid][1]-goal[rid][1]) <= arrival_radius_m:
                # Find the active task at this location assigned to rid
                for tr in active_tasks:
                    if tr["assigned_primary"] != rid or tr["state"] != "active":
                        continue
                    if math.hypot(tr["x"]-pose[rid][0], tr["y"]-pose[rid][1]) > arrival_radius_m:
                        continue
                    if tr["type"] == "deterring":
                        # Start hold if not started; else complete when time passed
                        if tr["started_hold"] is None:
                            tr["started_hold"] = t
                            loiter_until[rid] = t + hold_time_s
                        elif t >= tr["started_hold"] + hold_time_s:
                            tr["state"] = "done"
                            completed_tasks.append(tr)
                            robots[rid].ingest_intervention_event(tr["x"], tr["y"], t, weight=1.0)
                            b = robots[rid].intervention_boundary_events(tr["x"], tr["y"], t, weight=1.0)
                            EventBus(robots).send_intervention_events(b, source_id=rid)
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

                        if mon is not None and getattr(mon, 'enabled', False):
                            mon.event_task('complete', tr)

                        active_tasks[:] = [x for x in active_tasks if x["id"] != tr["id"]]
                        goal[rid] = None
                        break

        # Telemetry: per-step poses + hotspots + periodic flush
        if mon is not None and getattr(mon, 'enabled', False):
            for rid in robots:
                px, py = pose[rid]
                mon.pose(t, rid, px, py)
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
            mon.flush_live('telemetry_live', min_interval_s=0.5)

        # 5) Advance SESTPP time
        for rob in robots.values():
            rob.advance_time(dt)

        # 6) Yield frame snapshot
        yield {
            "t": t,
            "W": W, "H": H, "boundary": boundary,
            "cells": list(cells),
            "poses": {rid: tuple(pose[rid]) for rid in pose},
            "profiles": profiles,
            "tasks_active": list(active_tasks),
            "tasks_done": list(completed_tasks)
        }

        t += dt


def animate_demo_persistent(save_path=None, fps=5, duration_s=120, **sim_kwargs):
    frames = run_simulation_frames_persistent(dt=1.0, T_end=duration_s, fps=fps, **sim_kwargs)

    first = next(frames)
    W, H = first["W"], first["H"]
    fig, ax = plt.subplots(figsize=(8,6))
    ax.set_aspect('equal', adjustable='box')
    ax.set_xlim(-10, W+10); ax.set_ylim(-10, H+10)
    bx,by = zip(* (first["boundary"] + [first["boundary"][0]]) )
    (boundary_line,) = ax.plot(bx, by, 'k-', lw=1)

    # zone patches
    zone_patches = []
    for cell in first["cells"]:
        if not cell:
            zone_patches.append(None); continue
        p = MplPolygon(cell, closed=True, fill=True, alpha=0.10, edgecolor='k', facecolor='#bbbbff')
        ax.add_patch(p); zone_patches.append(p)

    # robot scatters
    uav_sc = ax.scatter([], [], s=60, c='#ff7f0e', edgecolors='k', zorder=3, label='UAV')
    ugv_sc = ax.scatter([], [], s=60, c='#1f77b4', edgecolors='k', zorder=3, label='UGV')

    # task scatters: active & completed
    det_act = ax.scatter([], [], s=80, c='red', marker='x', zorder=4, label='Deterring (active)')
    pat_act = ax.scatter([], [], s=60, c='blue', marker='D', zorder=4, label='Patrolling (active)')
    done_sc = ax.scatter([], [], s=30, c='#888888', marker='o', alpha=0.6, zorder=2, label='Completed')

    title = ax.set_title("")
    ax.legend(loc='upper right')

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
        # tasks
        xd,yd,xp,yp,xz,yz = _split_tasks(first["tasks_active"], first["tasks_done"])
        det_act.set_offsets(np.c_[xd,yd] if xd else np.empty((0,2)))
        pat_act.set_offsets(np.c_[xp,yp] if xp else np.empty((0,2)))
        done_sc.set_offsets(np.c_[xz,yz] if xz else np.empty((0,2)))
        title.set_text(f"t = {int(first['t'])} s")
        return (*[p for p in zone_patches if p], uav_sc, ugv_sc, det_act, pat_act, done_sc, boundary_line, title)

    def update(_):
        try:
            snap = next(frames)
        except StopIteration:
            return (*[p for p in zone_patches if p], uav_sc, ugv_sc, det_act, pat_act, done_sc, boundary_line, title)

        # zones
        for patch, cell in zip(zone_patches, snap["cells"]):
            if patch is None or not cell: continue
            patch.set_xy(cell)

        # robots
        xu,yu,xg,yg = _split_robot_points(snap["poses"], snap["profiles"])
        uav_sc.set_offsets(np.c_[xu,yu] if xu else np.empty((0,2)))
        ugv_sc.set_offsets(np.c_[xg,yg] if xg else np.empty((0,2)))

        # tasks
        xd,yd,xp,yp,xz,yz = _split_tasks(snap["tasks_active"], snap["tasks_done"])
        det_act.set_offsets(np.c_[xd,yd] if xd else np.empty((0,2)))
        pat_act.set_offsets(np.c_[xp,yp] if xp else np.empty((0,2)))
        done_sc.set_offsets(np.c_[xz,yz] if xz else np.empty((0,2)))

        title.set_text(f"t = {int(snap['t'])} s")
        return (*[p for p in zone_patches if p], uav_sc, ugv_sc, det_act, pat_act, done_sc, boundary_line, title)

    anim = FuncAnimation(fig, update, init_func=init,
                         frames=int(fps * (sim_kwargs.get("T_end", duration_s)/dt if "T_end" in sim_kwargs else duration_s)),
                         interval=1000/fps, blit=False, repeat=False)

    if save_path:
        anim.save(save_path, fps=fps, dpi=130)
    plt.show()
    return anim


if __name__ == "__main__":  
    animate_demo_persistent()