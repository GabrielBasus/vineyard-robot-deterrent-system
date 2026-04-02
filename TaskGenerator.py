from typing import Dict, List, Mapping
from Robot import Robot
from ZonePartitioner import polygon_area, polygon_centroid, point_in_polygon, point_to_poly_distance, Point
from Robot import RobotProfile
import math
import numpy as np

def _time_integral_factor(decay_s: float, horizon_s: float) -> float:
    decay_s = max(float(decay_s), 1e-9)
    horizon_s = max(float(horizon_s), 0.0)
    return float(decay_s * (1.0 - math.exp(-horizon_s / decay_s)))

def _normalized_gaussian_kernel(dx: float, dy: float, sigma: float) -> tuple[int, np.ndarray]:
    sigma = max(float(sigma), 1e-9)
    grid_step = max(float(dx), float(dy), 1e-9)
    rad = int(math.ceil(3.0 * sigma / grid_step))
    kx = np.arange(-rad, rad + 1, dtype=float)
    ky = np.arange(-rad, rad + 1, dtype=float)
    KX, KY = np.meshgrid(kx, ky, indexing="xy")
    dist2 = (KX * float(dx)) ** 2 + (KY * float(dy)) ** 2
    kernel = np.exp(-0.5 * dist2 / (sigma ** 2))
    total = float(np.sum(kernel))
    if total > 0.0:
        kernel /= total
    return rad, kernel

def estimate_counterfactual_reduction(
    model,
    x: float,
    y: float,
    *,
    beta_u: float,
    sigma_u: float,
    omega_u: float,
    horizon_s: float,
    mask_poly=None,
    weight_fn=None,
    value_edge_gain: float = 0.5,
    value_edge_scale: float = 30.0,
    value_block_gain: float = 0.3,
    value_block_size: float = 80.0,
    baseline_grid: np.ndarray | None = None,
    available_integral_grid: np.ndarray | None = None,
) -> dict:
    """Approximate Eq. (5) with a local grid patch and capped suppression.

    The no-action term uses the current positive excess above the local
    background baseline and propagates it over the horizon with the SESTPP
    excitation decay. The action term uses the mode's added inhibition
    footprint and decay. Per cell, the reduction is capped by the available
    excess integral so we do not count already-suppressed or below-baseline
    mass twice.
    """
    if baseline_grid is None:
        baseline_grid = model.mu * model.time_multiplier(model.t_now)
    if available_integral_grid is None:
        risk_factor = _time_integral_factor(model.omega, horizon_s)
        available_integral_grid = np.clip(model.lam - baseline_grid, 0.0, None) * risk_factor

    suppress_factor = _time_integral_factor(omega_u, horizon_s)
    footprint_rad, footprint_kernel = _normalized_gaussian_kernel(model.dx, model.dy, sigma_u)
    iy, ix = model.world_to_idx(x, y)
    y0 = max(0, iy - footprint_rad)
    y1 = min(model.ny, iy + footprint_rad + 1)
    x0 = max(0, ix - footprint_rad)
    x1 = min(model.nx, ix + footprint_rad + 1)
    ky0 = y0 - (iy - footprint_rad)
    ky1 = ky0 + (y1 - y0)
    kx0 = x0 - (ix - footprint_rad)
    kx1 = kx0 + (x1 - x0)
    patch_kernel = footprint_kernel[ky0:ky1, kx0:kx1]

    delta_a = float(model.dx * model.dy)
    suppression_amp = float(model.alpha_inhib) * float(beta_u)
    predicted_reduction_raw = 0.0
    available_weighted = 0.0
    suppression_weighted = 0.0
    contributing_cells = 0

    for yy in range(y0, y1):
        wy = float(model.ys[yy])
        for xx in range(x0, x1):
            wx = float(model.xs[xx])
            if (mask_poly is not None) and (not point_in_polygon(wx, wy, mask_poly)):
                continue
            if weight_fn is not None:
                weight = float(weight_fn(wx, wy))
            else:
                dist_edge = point_to_poly_distance((wx, wy), mask_poly) if mask_poly else 0.0
                edge_w = float(value_edge_gain) * math.exp(-dist_edge / max(float(value_edge_scale), 1e-9))
                bx = math.sin(2.0 * math.pi * wx / max(float(value_block_size), 1e-9))
                by = math.sin(2.0 * math.pi * wy / max(float(value_block_size), 1e-9))
                block_w = float(value_block_gain) * (0.5 + 0.5 * bx * by)
                weight = 1.0 + edge_w + block_w
            if weight <= 0.0:
                continue

            available_here = float(available_integral_grid[yy, xx])
            if available_here <= 0.0:
                continue

            kernel_val = float(patch_kernel[yy - y0, xx - x0])
            if kernel_val <= 0.0:
                continue

            suppression_here = suppression_amp * kernel_val * suppress_factor
            reduction_here = min(available_here, suppression_here)
            weighted_available_here = weight * available_here * delta_a
            weighted_suppression_here = weight * suppression_here * delta_a
            predicted_reduction_raw += weight * reduction_here * delta_a
            available_weighted += weighted_available_here
            suppression_weighted += weighted_suppression_here
            contributing_cells += 1

    return {
        "predicted_reduction_raw": float(predicted_reduction_raw),
        "available_weighted_integral": float(available_weighted),
        "suppression_weighted_integral": float(suppression_weighted),
        "contributing_cells": int(contributing_cells),
    }

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
        self._fallback_patrol_state: dict[str, dict] = {}
        # Per-robot cluster memory for preventive model-scored deterring gates.
        self._deterring_cluster_state: dict[tuple[str, int, int], dict] = {}
        self._deterring_forecast_state: dict[tuple[str, str, int, int], dict] = {}
        self._last_model_deterring_fire: dict[tuple, dict] = {}
        self._diag_model_deterring_llr_values: list[float] = []
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
        }

    def _diag_increment(self, key: str, amount=1):
        self.diag_counts[key] = self.diag_counts.get(key, 0) + amount

    def _diag_increment_source(self, prefix: str, origin: str, amount: int = 1):
        origin_key = (
            str(origin).strip().lower().replace("-", "_").replace(" ", "_")
            or "unknown"
        )
        self._diag_increment(f"{prefix}_{origin_key}", int(amount))

    def _fallback_zone_key(self, zone_polygon) -> tuple:
        if not zone_polygon:
            return ()
        return tuple(
            (round(float(x), 3), round(float(y), 3))
            for (x, y) in zone_polygon
        )

    def _fallback_waypoints(self, zone_polygon) -> list[tuple[float, float]]:
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
                             value_block_size: float = 80.0):
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

        for rid, rob in robots.items():
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
                if patrol_field_cache["excess"] is None:
                    if abs(patrol_inhib_retention - 1.0) <= 1e-12:
                        patrol_field_cache["excess"] = (rob.m.lam - rob.m.mu).copy()
                    else:
                        base_lam = rob.m.mu * rob.m.time_multiplier(rob.m.t_now) + rob.m.trigger_mass
                        patrol_lam = np.clip(base_lam - patrol_inhib_retention * rob.m.inhib_mass, 0.0, None)
                        patrol_field_cache["excess"] = patrol_lam - rob.m.mu
                return patrol_field_cache["excess"]

            def _patrol_field_score(x, y):
                if abs(patrol_inhib_retention - 1.0) <= 1e-12:
                    return _field_score(x, y)
                iy, ix = rob.m.world_to_idx(x, y)
                return float(_patrol_field_grid()[iy, ix])

            def _patrol_hotspots(top_k, merge_radius, mask_poly):
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

            def _weight_at(x, y):
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
                iy, ix = rob.m.world_to_idx(x, y)
                return float(rob.m.lam[iy, ix] - rob.m.mu[iy, ix])

            baseline_grid = rob.m.mu * rob.m.time_multiplier(rob.m.t_now)
            available_excess_integral_grid = (
                np.clip(rob.m.lam - baseline_grid, 0.0, None)
                * _time_integral_factor(rob.m.omega, horizon_s)
            )

            def _risk_confidence(x, y):
                # Map local excess intensity to [0,1) confidence.
                fs = max(0.0, _field_score(x, y))
                scale = max(float(deterring_risk_scale), 1e-12)
                return 1.0 - math.exp(-fs / scale)

            def _patch_expectation_horizon(x, y, sigma_u, field_name):
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
                rx, ry = _robot_pose_guess(rob, robot_pose=(robot_poses or {}).get(rid))
                dist = math.hypot(x - rx, y - ry)
                speed = 1.0
                spin = 0.0
                if profiles is not None and rid in profiles:
                    prof = profiles[rid]
                    speed = max(float(prof.speed_mps), 1e-6)
                    if spinup_by_type is not None:
                        spin = float(spinup_by_type.get(prof.type, 0.0))
                w_eta = cost_w_eta if w_eta_override is None else float(w_eta_override)
                return w_eta * (dist / max(speed, 1e-6) + spin) + float(fixed_cost)

            def _eta_seconds(x, y):
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
                # Patrol uses forecast persistence of the field, not intervention persistence.
                time_factor = _time_integral_factor(rob.m.omega, horizon_s)
                delta_a = float(rob.m.dx * rob.m.dy)
                benefit = max(0.0, _patrol_field_score(x, y)) * max(_weight_at(x, y), 0.0) * time_factor * delta_a
                cost_eta = _cost_eta(x, y)
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
                lam_patch = _patch_expectation_horizon(x, y, sigma_u, "lam")
                lam_patch = max(lam_patch, 0.0)
                return float(1.0 - math.exp(-lam_patch))

            def _deterrence_candidate_metrics(x, y, mode):
                params = deterring_modes.get(mode, {})
                beta = float(params.get("beta", rob.m.alpha_inhib))
                omega_u = float(params.get("omega", rob.m.omega_inhib))
                sigma_u = float(params.get("sigma", rob.m.sigma))
                w_eta = float(params.get("w_eta", cost_w_eta))
                fixed_cost = float(params.get("fixed_cost", 0.0))
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
                cost_eta = _cost_eta(x, y, w_eta_override=w_eta, fixed_cost=fixed_cost)
                utility = predicted_reduction_raw - cost_eta
                return {
                    "predicted_reduction_raw": float(predicted_reduction_raw),
                    "predicted_deltaJ": float(predicted_reduction_raw),
                    "cost_eta": float(cost_eta),
                    "utility": float(utility),
                    "score": float(utility),
                    "deltaJ_per_cost": float(predicted_reduction_raw / max(cost_eta, 1e-6)),
                    "beta": float(beta),
                    "omega_u": float(omega_u),
                    "sigma_u": float(sigma_u),
                    "reduction_summary": reduction_summary,
                }

            def _deterring_selection_weight(cand):
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
                return (
                    rid,
                    int(round(float(x) / cluster_quant)),
                    int(round(float(y) / cluster_quant)),
                )

            def _candidate_key(origin, x, y):
                return (
                    rid,
                    str(origin).strip().lower(),
                    int(round(float(x) / preventive_quant)),
                    int(round(float(y) / preventive_quant)),
                )

            def _origin_is_detection_cluster(origin):
                return str(origin).strip().lower() == "model_detection_cluster"

            def _origin_is_forecast_hotspot(origin):
                return str(origin).strip().lower() in ("model_hotspot", "model_border_hotspot")

            def _near_any(x, y, pts, radius2):
                return any(((x - px) ** 2 + (y - py) ** 2) <= radius2 for (px, py) in pts)

            def _collect_border_hotspots(top_k):
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

            patrol_candidates = []
            preventive_candidate_seeds = []
            preventive_seed_points = []

            def _register_preventive_seed(x, y, origin, forecast_score=0.0):
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
                    for mode in deterring_modes.keys():
                        mode_metrics = _deterrence_candidate_metrics(dx, dy, mode)
                        params = deterring_modes.get(mode, {})
                        mode_cost = float(mode_metrics["cost_eta"])
                        sigma_u = float(params.get("sigma", rob.m.sigma))
                        mode_p_event = _event_probability(dx, dy, sigma_u)
                        mode_predicted_deltaJ = float(mode_metrics["predicted_deltaJ"])
                        mode_utility = float(mode_metrics["utility"])
                        mode_score = float(mode_metrics["score"])
                        mode_deltaJ_per_cost = float(mode_metrics["deltaJ_per_cost"])
                        if best_mode is None or mode_utility > best_mode_utility:
                            best_mode = mode
                            best_mode_utility = mode_utility
                            best_mode_score = mode_score
                            best_mode_cost = mode_cost
                            best_mode_event_prob = mode_p_event
                            best_mode_deltaJ_per_cost = mode_deltaJ_per_cost
                            best_mode_predicted_deltaJ = mode_predicted_deltaJ

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
                            "llr": float(llr),
                            "recent_detection_count": int(recent_detection_count),
                            "patch_area": float(patch_area),
                            "patch_mu0": float(patch_mu0),
                            "patch_mu1": float(patch_mu1),
                            "p_event": float(best_mode_event_prob or 0.0),
                            "deltaJ_per_cost": float(best_mode_deltaJ_per_cost or 0.0),
                            "cost_eta": float(best_mode_cost or 0.0),
                            "forecast_score": float(seed.get("forecast_score", 0.0)),
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
                    task_added = self._add({
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
                        'p_event': float(best.get("p_event", 0.0)),
                        'deltaJ_per_cost': float(best.get("deltaJ_per_cost", 0.0)),
                        'llr': float(best.get("llr", 0.0)),
                        'selection_weight': float(best.get("selection_weight", 1.0)),
                        'posterior_h1': float(best.get("posterior_h1", float("nan"))),
                        'count_excess_ratio': float(best.get("count_excess_ratio", float("nan"))),
                    })
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

            # fallback if nothing for this robot at this time slice
            if include_fallback_patrol and not self._has_robot_at_time(rid, now_t):
                cx, cy = self._select_fallback_patrol_point(rid, rob)
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
            'score': float(task.get('score', 0.0)),
            'utility': float(task.get('utility', task.get('score', 0.0))),
            'support': int(task.get('support', 0)),
            'risk_conf': float(task.get('risk_conf', 0.0)),
            'eta_s': float(task.get('eta_s', 0.0)),
            'cost_eta': float(task.get('cost_eta', 0.0)),
            'persistence': int(task.get('persistence', 0)),
            'predicted_deltaJ': float(task.get('predicted_deltaJ', 0.0)),
            'p_event': float(task.get('p_event', 0.0)),
            'deltaJ_per_cost': float(task.get('deltaJ_per_cost', 0.0)),
            'llr': float(task.get('llr', 0.0)),
            'selection_weight': float(task.get('selection_weight', 1.0)),
            'posterior_h1': float(task.get('posterior_h1', float("nan"))),
            'count_excess_ratio': float(task.get('count_excess_ratio', float("nan"))),
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

    def set_load(self, load_by_robot: dict[str, int]):
        self.load_by_robot = {str(k): int(v) for k, v in (load_by_robot or {}).items()}

    def set_robot_poses(self, robot_poses: Mapping[str, tuple[float, float]] | None):
        self.robot_poses = {
            str(k): (float(v[0]), float(v[1]))
            for k, v in (robot_poses or {}).items()
            if v is not None
        }

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
            if task.get("type") == "deterring":
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
        if task["type"] == "deterring" and len(scored) > 1:
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
        rx, ry = _robot_pose_guess(rob, robot_pose=self.robot_poses.get(prof.id))
        dist = math.hypot(task["x"] - rx, task["y"] - ry)

        spin = w["uav_spinup_s"] if prof.type == "UAV" else w["ugv_spinup_s"]
        eta = dist / max(prof.speed_mps, 1e-6) + spin

        cap = prof.deterrent_eff if task["type"] == "deterring" else 1.0
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

def _robot_pose_guess(rob: "Robot", robot_pose: tuple[float, float] | None = None) -> tuple[float,float]:
    """
    If you don't track live robot poses yet, use the zone centroid as a proxy.
    Replace with your real (x,y) when available.
    """
    if robot_pose is not None:
        return float(robot_pose[0]), float(robot_pose[1])
    cx, cy = polygon_centroid(rob.zone_polygon)
    return float(cx), float(cy)
