from typing import Dict, List
from Robot import Robot
from ZonePartitioner import polygon_centroid, point_in_polygon, Point
from Robot import RobotProfile
import math

def cluster_points(points: List[Point], radius: float) -> List[Point]:
    pts = points[:]
    out = []
    while pts:
        p = pts.pop()
        cluster = [p]
        rest = []
        for q in pts:
            if (p[0]-q[0])**2 + (p[1]-q[1])**2 <= radius**2:
                cluster.append(q)
            else:
                rest.append(q)
        pts = rest
        xs = [c[0] for c in cluster]; ys=[c[1] for c in cluster]
        out.append((sum(xs)/len(xs), sum(ys)/len(ys)))
    return out

class TaskGenerator:
    def __init__(self, merge_radius_m: float = 20.0, dedupe_xy_decimals: int = 1, dedupe_t_decimals: int = 0,
                 patrol_cooldown_s: float = 20.0):
        self.merge_radius_m = float(merge_radius_m)
        self._rows = []
        self._keys = set()  # (robot_id,type,round(x,d),round(y,d),round(t,d))

        self._dx = dedupe_xy_decimals
        self._dt = dedupe_t_decimals
        self._cooldown = float(patrol_cooldown_s)
        self._next_allowed: dict[str,float] = {}  # per-robot next allowed time for patrolling

    # -------- immediate tasks (called right when detections arrive) --------
    def on_detection(self, robot_id: str, x: float, y: float, t: float):
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
                             include_fallback_patrol: bool = False,
                             deterring_window_s: float = 0.0,
                             min_hotspot_score: float = 1e-4,
                             hotspot_spacing_m: float = 25.0,
                             jitter_m: float = 4.0,
                             horizon_s: float = 300.0,
                             cost_per_m: float = 0.0,
                             weight_fn=None):
        """
        Build patrolling-from-hotspots tasks for each robot at 'now_t'.
        Optionally keep a small deterring window if you also want clustered deterring here.
        By default deterring_window_s=0 to avoid duplicating immediate tasks.
        """
        for rid, rob in robots.items():
            # keep model time consistent
            rob.m.advance_time(now_t - rob.m.t_now)

            # recent detections (for optional clustered deterring here)
            recent_pts = [(x,y) for (x,y,t) in rob.recent_events if (now_t - t) <= deterring_window_s]
            deterring_points = cluster_points(recent_pts, self.merge_radius_m) if deterring_window_s > 0 else []

            # hotspots from SESTPP excess lambda-mu
            # Get more candidates than we'll keep, then thin for spacing
            raw = rob.m.hotspots(
                top_k=max(hotspot_top_k*3, hotspot_top_k),
                merge_radius=max(self.merge_radius_m, hotspot_spacing_m*0.5),
                use_excess=True,
                mask_poly=rob.zone_polygon
            )
            # Score filter + Poisson-disk style thinning
            cand = [(h['x'], h['y'], h['score']) for h in raw if h.get('score', 0.0) >= min_hotspot_score]
            picks = []
            for (hx, hy, hs) in cand:
                if any((hx-px)**2 + (hy-py)**2 <= hotspot_spacing_m**2 for (px,py,_) in picks):
                    continue
                picks.append((hx, hy, hs))

            # avoid hotspots that coincide with deterring clusters
            # Add a tiny random jitter to decorrelate grid alignment
            import random, math

            def _weight_at(x, y):
                return float(weight_fn(x, y)) if weight_fn is not None else 1.0

            def _field_score(x, y):
                iy, ix = rob.m.world_to_idx(x, y)
                return float(rob.m.lam[iy, ix] - rob.m.mu[iy, ix])

            def _action_score(x, y, base_score):
                # Expected future reduction proxy using inhibition time constant.
                omega_u = float(rob.m.omega_inhib)
                time_factor = omega_u * (1.0 - math.exp(-horizon_s / max(omega_u, 1e-9)))
                w = _weight_at(x, y)
                rx, ry = _robot_pose_guess(rob)
                dist = math.hypot(x - rx, y - ry)
                return w * base_score * time_factor - cost_per_m * dist

            # Build candidate list: hotspots (patrolling) + optional deterring clusters
            candidates = []
            for (hx, hy, hs) in picks:
                if any((hx-dx)**2 + (hy-dy)**2 <= self.merge_radius_m**2 for (dx,dy) in deterring_points):
                    continue
                candidates.append(("patrolling", hx, hy, float(hs), "hotspot"))

            for (dx, dy) in deterring_points:
                base = _field_score(dx, dy)
                candidates.append(("deterring", dx, dy, base, "detection"))

            # Cooldown gate for patrols per robot
            next_ok = self._next_allowed.get(rid, -1e9)
            if now_t >= next_ok and candidates:
                best = None
                for (ttype, x, y, base, origin) in candidates:
                    if base < min_hotspot_score:
                        continue
                    score = _action_score(x, y, base)
                    if best is None or score > best[0]:
                        best = (score, ttype, x, y, origin, base)

                if best is not None:
                    _score, ttype, x, y, origin, base = best
                    jx = (random.uniform(-1,1) * jitter_m) if ttype == "patrolling" else 0.0
                    jy = (random.uniform(-1,1) * jitter_m) if ttype == "patrolling" else 0.0
                    self._add({
                        'robot_id': rid,
                        'type': ttype,
                        'x': float(x + jx), 'y': float(y + jy),
                        'time': float(now_t),
                        'origin': origin,
                        'score': float(_score)
                    })
                    self._next_allowed[rid] = now_t + self._cooldown

            # fallback if nothing for this robot at this time slice
            # Optional fallback (off by default). If you re-enable it, consider
            # sweeping around the zone instead of always choosing the centroid.
            if include_fallback_patrol and not self._has_robot_at_time(rid, now_t):
                cx, cy = polygon_centroid(rob.zone_polygon)
                self._add({
                    'robot_id': rid,
                    'type': 'patrolling',
                    'x': float(cx), 'y': float(cy),
                    'time': float(now_t),
                    'origin': 'fallback',
                    'score': 0.0
                })

    # -------- utilities --------
    def rows(self):
        return list(self._rows)

    def clear(self):
        self._rows.clear()
        self._keys.clear()

    def _has_robot_at_time(self, rid: str, t: float) -> bool:
        # quick presence check by scanning keys (rounded time)
        rt = round(float(t), self._dt)
        for (krid, _kt, _kx, _ky, kt) in self._keys:
            if krid == rid and kt == rt:
                return True
        return False

    def _add(self, task: Dict):
        key = (
            task['robot_id'],
            task['type'],
            round(float(task['x']), self._dx),
            round(float(task['y']), self._dx),
            round(float(task['time']), self._dt),
        )
        if key in self._keys:
            return
        self._keys.add(key)
        self._rows.append({
            'robot_id': task['robot_id'],
            'type': task['type'],                         # 'deterring' or 'patrolling'
            'x': float(task['x']),
            'y': float(task['y']),
            'time': float(task['time']),
            'origin': task.get('origin', 'unknown'),      # 'detection'|'hotspot'|'fallback'
            'score': float(task.get('score', 0.0)),
        })

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

    # ---------- public API ----------
    def assign_task(self, task: dict) -> dict | None:
        """
        Returns an assignment dict:
          {task: <task>, primary: <robot_id>, secondary: <robot_id or None>, details: {...}}
        or None if no eligible robot.
        """
        eligible = [rid for rid in self.P if self._eligible(self.P[rid], task)]
        if not eligible:
            return None

        scored = [(self._score(self.P[rid], task), rid) for rid in eligible]
        scored.sort(reverse=True, key=lambda x: x[0])
        primary = scored[0][1]

        secondary = None
        if task["type"] == "deterring" and len(scored) > 1:
            # pick a second unit for handoff/sustain (prefer UGV if primary is UAV)
            for _, rid in scored[1:]:
                if self.P[primary].type == "UAV" and self.P[rid].type == "UGV":
                    secondary = rid; break
            if secondary is None:
                secondary = scored[1][1]

        return {"task": task, "primary": primary, "secondary": secondary, "details": {"scores": scored[:3]}}

    # ---------- helpers ----------
    def _eligible(self, prof: RobotProfile, task: dict) -> bool:
        # battery thresholds by task type
        min_batt = self.w["min_batt_deterring"] if task["type"] == "deterring" else self.w["min_batt_patrolling"]
        if prof.battery < min_batt or prof.health < 0.15:
            return False
        if task["type"] == "deterring" and not prof.has_deterrent:
            return False
        # (extend here with airspace/terrain checks as needed)
        return True

    def _score(self, prof: RobotProfile, task: dict) -> float:
        w = self.w
        prio = w["prio_deterring"] if task["type"] == "deterring" else w["prio_patrolling"]

        # Distance from robot to task. Use robot anchor or zone centroid as current pose.
        rob = self.R[prof.id]
        rx, ry = _robot_pose_guess(rob)
        dist = math.hypot(task["x"] - rx, task["y"] - ry)

        spin = w["uav_spinup_s"] if prof.type == "UAV" else w["ugv_spinup_s"]
        eta = dist / max(prof.speed_mps, 1e-6) + spin

        cap = prof.deterrent_eff if task["type"] == "deterring" else 1.0
        zone_bonus = 1.0 if point_in_polygon(task["x"], task["y"], rob.zone_polygon) else 0.0

        return (w["w_cap"]   * cap
              - w["w_eta"]   * eta
              + w["w_stay"]  * prof.endurance_min
              + w["w_zone"]  * zone_bonus
              + w["w_health"]* prof.health
              + w["w_prio"]  * prio)

def _robot_pose_guess(rob: "Robot") -> tuple[float,float]:
    """
    If you don't track live robot poses yet, use the zone centroid as a proxy.
    Replace with your real (x,y) when available.
    """
    cx, cy = polygon_centroid(rob.zone_polygon)
    return float(cx), float(cy)
