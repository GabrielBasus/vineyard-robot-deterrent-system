from typing import Dict, List
from Robot import Robot
from ZonePartitioner import polygon_centroid, point_in_polygon, point_to_poly_distance, Point
from Robot import RobotProfile
import math
import numpy as np

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
        self._last_model_deterring_fire: dict[tuple[str, int, int], dict] = {}
        self._debug_patrol_pipeline: dict[str, dict] = {}
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
            "model_deterring_pass_chance": 0,
            "model_deterring_rejected_chance": 0,
            "model_deterring_pass_utility_ratio": 0,
            "model_deterring_rejected_utility_ratio": 0,
            "model_deterring_pass_capacity": 0,
            "model_deterring_rejected_capacity": 0,
            "model_deterring_llr_sum": 0.0,
            "model_deterring_llr_samples": 0,
            "model_deterring_llr_max": float("-inf"),
            "model_deterring_p_event_sum": 0.0,
            "model_deterring_p_event_samples": 0,
            "model_deterring_deltaJ_per_cost_sum": 0.0,
            "model_deterring_deltaJ_per_cost_samples": 0,
        }

    def patrol_debug_snapshot(self) -> dict[str, dict]:
        return {
            str(rid): {
                "local_hotspots_raw": [dict(row) for row in stages.get("local_hotspots_raw", [])],
                "local_hotspots_score_filtered": [dict(row) for row in stages.get("local_hotspots_score_filtered", [])],
                "local_hotspots_spaced": [dict(row) for row in stages.get("local_hotspots_spaced", [])],
                "raw_patrol_candidates": [dict(row) for row in stages.get("raw_patrol_candidates", [])],
                "score_stats": dict(stages.get("score_stats", {})),
            }
            for rid, stages in self._debug_patrol_pipeline.items()
        }

    def _stable_mc_seed(self, rid: str, now_t: float, salt: int = 0) -> int:
        seed = 2166136261
        for ch in str(rid):
            seed = ((seed ^ ord(ch)) * 16777619) & 0xFFFFFFFF
        seed = ((seed ^ int(round(float(now_t) * 10.0))) * 16777619) & 0xFFFFFFFF
        seed = ((seed ^ int(salt)) * 16777619) & 0xFFFFFFFF
        return int(seed)

    def _rank_field_points(self, field, xs, ys, top_k: int, merge_radius: float, mask_poly=None) -> List[Dict]:
        arr = np.asarray(field, dtype=float)
        if arr.size == 0:
            return []
        k_short = min(arr.size, max(5 * int(top_k), int(top_k)))
        flat_idx = np.argpartition(arr.ravel(), -k_short)[-k_short:]
        flat_sorted = flat_idx[np.argsort(arr.ravel()[flat_idx])[::-1]]
        picks = []
        coords = []
        nx = int(len(xs))
        for idx in flat_sorted:
            iy, ix = divmod(int(idx), nx)
            score = float(arr[iy, ix])
            if score <= 0.0:
                continue
            x = float(xs[ix])
            y = float(ys[iy])
            if mask_poly and (not point_in_polygon(x, y, mask_poly)):
                continue
            if any((x - px) ** 2 + (y - py) ** 2 <= merge_radius ** 2 for (px, py) in coords):
                continue
            coords.append((x, y))
            picks.append({"x": x, "y": y, "score": score})
            if len(picks) >= int(top_k):
                break
        return picks

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
            cx, cy = polygon_centroid(rob.zone_polygon)
            return float(cx), float(cy)

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

    def _monte_carlo_patrol_points(
        self,
        *,
        rob: "Robot",
        rid: str,
        now_t: float,
        hotspot_top_k: int,
        merge_radius: float,
        mask_poly,
        use_excess: bool,
        horizon_s: float,
        rollouts: int,
        max_events_per_rollout: int,
    ) -> tuple[list[dict], dict]:
        xs = np.asarray(rob.m.xs, dtype=float)
        ys = np.asarray(rob.m.ys, dtype=float)
        area = float(rob.m.dx * rob.m.dy)
        horizon = max(float(horizon_s), 1e-6)
        rollouts = max(1, int(rollouts))
        max_events_per_rollout = max(1, int(max_events_per_rollout))
        raw_top_k = max(int(hotspot_top_k), 6 * int(hotspot_top_k))

        base_field = np.asarray(rob.m.lam - rob.m.mu if use_excess else rob.m.lam, dtype=float)
        field = np.clip(base_field, 0.0, None)
        if mask_poly:
            mask = np.zeros_like(field, dtype=bool)
            for iy, wy in enumerate(ys):
                for ix, wx in enumerate(xs):
                    if point_in_polygon(float(wx), float(wy), mask_poly):
                        mask[iy, ix] = True
            field = np.where(mask, field, 0.0)

        event_mass = field * area * horizon
        total_mean = float(np.sum(event_mass))
        positive = np.flatnonzero(event_mass.ravel() > 0.0)
        meta = {
            "generation_mode": "monte_carlo",
            "mc_rollouts": int(rollouts),
            "mc_horizon_s": float(horizon),
            "mc_use_excess": bool(use_excess),
            "mc_total_expected_events": float(total_mean),
            "mc_total_samples": 0,
            "mc_nonzero_cells": 0,
            "mc_fallback_used": False,
        }

        if positive.size == 0 or total_mean <= 0.0:
            meta["mc_fallback_used"] = True
            fallback = self._rank_field_points(
                field=field,
                xs=xs,
                ys=ys,
                top_k=raw_top_k,
                merge_radius=float(merge_radius),
                mask_poly=mask_poly,
            )
            return fallback, meta

        probs = event_mass.ravel()[positive].astype(float)
        probs_sum = float(np.sum(probs))
        if probs_sum <= 0.0:
            meta["mc_fallback_used"] = True
            fallback = self._rank_field_points(
                field=field,
                xs=xs,
                ys=ys,
                top_k=raw_top_k,
                merge_radius=float(merge_radius),
                mask_poly=mask_poly,
            )
            return fallback, meta
        probs /= probs_sum

        rng = np.random.default_rng(
            self._stable_mc_seed(
                rid,
                now_t,
                salt=(31 * int(hotspot_top_k) + 17 * int(rollouts) + int(use_excess)),
            )
        )
        sample_counts = np.zeros(event_mass.size, dtype=np.int64)
        total_samples = 0
        for _ in range(rollouts):
            n_events = int(rng.poisson(total_mean))
            n_events = min(n_events, max_events_per_rollout)
            if n_events <= 0:
                continue
            draws = rng.choice(positive, size=n_events, replace=True, p=probs)
            sample_counts += np.bincount(draws, minlength=event_mass.size)
            total_samples += n_events

        meta["mc_total_samples"] = int(total_samples)
        sampled = np.flatnonzero(sample_counts > 0)
        meta["mc_nonzero_cells"] = int(sampled.size)

        if sampled.size == 0:
            meta["mc_fallback_used"] = True
            fallback = self._rank_field_points(
                field=field,
                xs=xs,
                ys=ys,
                top_k=raw_top_k,
                merge_radius=float(merge_radius),
                mask_poly=mask_poly,
            )
            return fallback, meta

        sampled_scores = sample_counts[sampled].astype(float) / float(rollouts)
        order = sampled[np.argsort(sampled_scores)[::-1]]
        raw = []
        for idx in order[:raw_top_k]:
            iy, ix = divmod(int(idx), int(rob.m.nx))
            raw.append(
                {
                    "x": float(xs[ix]),
                    "y": float(ys[iy]),
                    "score": float(sample_counts[idx]) / float(rollouts),
                }
            )
        return raw, meta

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
                             min_predicted_deltaJ_for_model_deterring: float = 0.0,
                             model_deterring_gate_policy: str = "heuristic",
                             model_deterring_sprt_alpha: float = 0.05,
                             model_deterring_sprt_beta: float = 0.20,
                             model_deterring_sprt_patch_radius_m: float | None = None,
                             model_deterring_chance_threshold: float = 0.20,
                             model_deterring_min_deltaJ_per_cost: float = 0.15,
                             preventive_capacity_remaining_by_robot: Dict[str, float] | None = None,
                             preventive_capacity_ready_by_robot: Dict[str, bool] | None = None,
                             replan_interval_s: float | None = None,
                             busy_deterring_robots=None,
                             recent_deterrence_events: List[dict] | None = None,
                             min_hotspot_score: float = 1e-4,
                             patrol_hotspot_filter_mode: str = "absolute",
                             patrol_hotspot_score_percentile: float = 90.0,
                             patrol_hotspot_keep_top_k: int | None = None,
                             patrol_point_generation_mode: str = "hotspots",
                             patrol_mc_rollouts: int = 64,
                             patrol_mc_max_events_per_rollout: int = 24,
                             patrol_mc_use_excess: bool = True,
                             hotspot_spacing_m: float = 25.0,
                             jitter_m: float = 4.0,
                             horizon_s: float = 300.0,
                             weight_fn=None,
                             profiles: Dict[str, RobotProfile] | None = None,
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
        gate_policy = str(model_deterring_gate_policy).strip().lower()
        if gate_policy not in ("heuristic", "sprt_capacity"):
            gate_policy = "heuristic"
        sprt_alpha = min(max(float(model_deterring_sprt_alpha), 1e-6), 1.0 - 1e-6)
        sprt_beta = min(max(float(model_deterring_sprt_beta), 1e-6), 1.0 - 1e-6)
        sprt_accept = math.log((1.0 - sprt_beta) / sprt_alpha)
        sprt_reject = math.log(sprt_beta / (1.0 - sprt_alpha))
        patch_radius = float(model_deterring_sprt_patch_radius_m) if model_deterring_sprt_patch_radius_m is not None else float(self.merge_radius_m)
        patch_radius = max(patch_radius, 1e-6)
        chance_threshold = min(max(float(model_deterring_chance_threshold), 0.0), 1.0)
        min_deltaJ_per_cost = float(model_deterring_min_deltaJ_per_cost)
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
        point_generation_mode = str(patrol_point_generation_mode).strip().lower()
        if point_generation_mode not in ("hotspots", "monte_carlo"):
            point_generation_mode = "hotspots"
        self._debug_patrol_pipeline = {}

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

            # hotspots from SESTPP excess lambda-mu
            # Get more candidates than we'll keep, then thin for spacing
            mask = rob.zone_polygon if rob.zone_polygon else None
            generation_meta = {"generation_mode": str(point_generation_mode)}
            if point_generation_mode == "monte_carlo":
                raw, generation_meta = self._monte_carlo_patrol_points(
                    rob=rob,
                    rid=str(rid),
                    now_t=float(now_t),
                    hotspot_top_k=int(hotspot_top_k),
                    merge_radius=max(self.merge_radius_m, hotspot_spacing_m * 0.5),
                    mask_poly=mask,
                    use_excess=bool(patrol_mc_use_excess),
                    horizon_s=float(horizon_s),
                    rollouts=int(patrol_mc_rollouts),
                    max_events_per_rollout=int(patrol_mc_max_events_per_rollout),
                )
            else:
                raw = rob.m.hotspots(
                    top_k=max(hotspot_top_k*3, hotspot_top_k),
                    merge_radius=max(self.merge_radius_m, hotspot_spacing_m*0.5),
                    use_excess=True,
                    mask_poly=mask
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
                if not math.isfinite(threshold_applied):
                    threshold_applied = float("nan")
                    filtered_hotspots = []
                else:
                    filtered_hotspots = [h for h in raw if float(h.get("score", 0.0)) >= threshold_applied]
            else:  # top_k
                ranked_hotspots = sorted(raw, key=lambda h: float(h.get("score", 0.0)), reverse=True)
                filtered_hotspots = ranked_hotspots[: int(keep_top_k)]
                threshold_applied = (
                    float(filtered_hotspots[-1].get("score", 0.0))
                    if filtered_hotspots else float("nan")
                )
            # Score filter + Poisson-disk style thinning
            cand = [(h['x'], h['y'], h['score']) for h in filtered_hotspots]
            picks = []
            for (hx, hy, hs) in cand:
                if any((hx-px)**2 + (hy-py)**2 <= hotspot_spacing_m**2 for (px,py,_) in picks):
                    continue
                picks.append((hx, hy, hs))
            patrol_debug = {
                "local_hotspots_raw": [
                    {
                        "robot_id": str(rid),
                        "x": float(h.get("x", 0.0)),
                        "y": float(h.get("y", 0.0)),
                        "score": float(h.get("score", 0.0)),
                    }
                    for h in raw
                ],
                "local_hotspots_score_filtered": [
                    {
                        "robot_id": str(rid),
                        "x": float(h.get("x", 0.0)),
                        "y": float(h.get("y", 0.0)),
                        "score": float(h.get("score", 0.0)),
                    }
                    for h in filtered_hotspots
                ],
                "local_hotspots_spaced": [
                    {
                        "robot_id": str(rid),
                        "x": float(hx),
                        "y": float(hy),
                        "score": float(hs),
                    }
                    for (hx, hy, hs) in picks
                ],
                "raw_patrol_candidates": [],
                "score_stats": {
                    "robot_id": str(rid),
                    "filter_mode": str(filter_mode),
                    "generation_mode": str(generation_meta.get("generation_mode", point_generation_mode)),
                    "threshold_applied": float(threshold_applied) if math.isfinite(threshold_applied) else float("nan"),
                    "raw_count": int(len(raw)),
                    "score_filtered_count": int(len(filtered_hotspots)),
                    "spaced_count": int(len(picks)),
                    "score_min": float(raw_scores[0]) if raw_scores else float("nan"),
                    "score_mean": float(sum(raw_scores) / len(raw_scores)) if raw_scores else float("nan"),
                    "score_p50": _quantile(raw_scores, 50.0),
                    "score_p75": _quantile(raw_scores, 75.0),
                    "score_p90": _quantile(raw_scores, 90.0),
                    "score_p95": _quantile(raw_scores, 95.0),
                    "score_max": float(raw_scores[-1]) if raw_scores else float("nan"),
                    "mc_total_expected_events": float(generation_meta.get("mc_total_expected_events", float("nan"))),
                    "mc_total_samples": float(generation_meta.get("mc_total_samples", float("nan"))),
                    "mc_nonzero_cells": float(generation_meta.get("mc_nonzero_cells", float("nan"))),
                    "mc_rollouts": float(generation_meta.get("mc_rollouts", float("nan"))),
                    "mc_horizon_s": float(generation_meta.get("mc_horizon_s", float("nan"))),
                    "mc_use_excess": bool(generation_meta.get("mc_use_excess", patrol_mc_use_excess)),
                    "mc_fallback_used": bool(generation_meta.get("mc_fallback_used", False)),
                },
            }

            # avoid hotspots that coincide with deterring clusters
            # Add a tiny random jitter to decorrelate grid alignment
            import random
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

            def _risk_confidence(x, y):
                # Map local excess intensity to [0,1) confidence.
                fs = max(0.0, _field_score(x, y))
                scale = max(float(deterring_risk_scale), 1e-12)
                return 1.0 - math.exp(-fs / scale)

            def _kernel_weight_sum_sigma(x, y, sigma_u):
                rad = int(math.ceil(3.0 * sigma_u / max(rob.m.dx, rob.m.dy)))
                iy, ix = rob.m.world_to_idx(x, y)
                y0 = max(0, iy - rad); y1 = min(rob.m.ny, iy + rad + 1)
                x0 = max(0, ix - rad); x1 = min(rob.m.nx, ix + rad + 1)
                acc = 0.0
                for yy in range(y0, y1):
                    wy = rob.m.ys[yy]
                    for xx in range(x0, x1):
                        wx = rob.m.xs[xx]
                        dx = wx - x
                        dy = wy - y
                        k = math.exp(-0.5 * (dx*dx + dy*dy) / max(sigma_u**2, 1e-9))
                        acc += _weight_at(wx, wy) * k
                return acc

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
                # SPRT should compare counts observed over the current count/replan window
                # against count-window expectations, not horizon-scale expectations.
                rad = int(math.ceil(3.0 * sigma_u / max(rob.m.dx, rob.m.dy)))
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
                        k = math.exp(-0.5 * (dxw * dxw + dyw * dyw) / max(sigma_u ** 2, 1e-9))
                        acc += float(field[yy, xx]) * k
                return max(delta_a * time_factor * acc, 1e-9)

            def _cost_eta(x, y, w_eta_override=None, fixed_cost=0.0):
                rx, ry = _robot_pose_guess(rob)
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
                rx, ry = _robot_pose_guess(rob)
                dist = math.hypot(x - rx, y - ry)
                speed = 1.0
                spin = 0.0
                if profiles is not None and rid in profiles:
                    prof = profiles[rid]
                    speed = max(float(prof.speed_mps), 1e-6)
                    if spinup_by_type is not None:
                        spin = float(spinup_by_type.get(prof.type, 0.0))
                return float(dist / max(speed, 1e-6) + spin)

            def _action_score_patrol(x, y):
                # Patrol: use local field as benefit proxy.
                omega_u = float(rob.m.omega_inhib)
                time_factor = omega_u * (1.0 - math.exp(-horizon_s / max(omega_u, 1e-9)))
                delta_a = float(rob.m.dx * rob.m.dy)
                benefit = _field_score(x, y) * time_factor * delta_a
                return benefit - _cost_eta(x, y)

            def _event_probability(x, y, sigma_u):
                lam_patch = _patch_expectation_horizon(x, y, sigma_u, "lam")
                lam_patch = max(lam_patch, 0.0)
                return float(1.0 - math.exp(-lam_patch))

            def _action_score_deterrence(x, y, mode):
                params = deterring_modes.get(mode, {})
                beta = float(params.get("beta", rob.m.alpha_inhib))
                omega_u = float(params.get("omega", rob.m.omega_inhib))
                sigma_u = float(params.get("sigma", rob.m.sigma))
                w_eta = float(params.get("w_eta", cost_w_eta))
                fixed_cost = float(params.get("fixed_cost", 0.0))
                time_factor = omega_u * (1.0 - math.exp(-horizon_s / max(omega_u, 1e-9)))
                delta_a = float(rob.m.dx * rob.m.dy)
                benefit = beta * time_factor * delta_a * _kernel_weight_sum_sigma(x, y, sigma_u)
                return benefit - _cost_eta(x, y, w_eta_override=w_eta, fixed_cost=fixed_cost)

            def _cluster_key(x, y):
                return (
                    rid,
                    int(round(float(x) / cluster_quant)),
                    int(round(float(y) / cluster_quant)),
                )

            # Build candidate list: hotspots (patrolling) + optional deterring clusters
            candidates = []
            for (hx, hy, hs) in picks:
                if any((hx-dx)**2 + (hy-dy)**2 <= self.merge_radius_m**2 for (dx,dy) in deterring_points):
                    continue
                patrol_candidate = {
                    "type": "patrolling",
                    "x": float(hx),
                    "y": float(hy),
                    "origin": "mc_patrol" if point_generation_mode == "monte_carlo" else "hotspot",
                    "mode": None,
                    "support": 0,
                    "persistence": 0,
                    "risk_conf": 0.0,
                    "eta_s": _eta_seconds(hx, hy),
                    "cluster_key": None,
                }
                candidates.append(patrol_candidate)
                patrol_debug["raw_patrol_candidates"].append(
                    {
                        "robot_id": str(rid),
                        "x": float(hx),
                        "y": float(hy),
                        "score": float(hs),
                        "eta_s": float(patrol_candidate["eta_s"]),
                    }
                )
            self._debug_patrol_pipeline[str(rid)] = patrol_debug

            current_cluster_keys = set()
            if enable_model_scored_deterring:
                for (dx, dy) in deterring_points:
                    support = sum(
                        1 for (rx, ry) in recent_pts
                        if ((rx - dx) ** 2 + (ry - dy) ** 2) <= (self.merge_radius_m ** 2)
                    )
                    recent_detection_count = sum(
                        1 for (rx, ry) in count_pts
                        if ((rx - dx) ** 2 + (ry - dy) ** 2) <= (patch_radius ** 2)
                    )
                    ck = _cluster_key(dx, dy)
                    current_cluster_keys.add(ck)
                    prev_state = self._deterring_cluster_state.get(ck)
                    if prev_state and (float(now_t) - float(prev_state.get("last_t", -1e9)) <= persist_gap_s):
                        persistence = int(prev_state.get("count", 0)) + 1
                    else:
                        persistence = 1
                    patch_mu0 = _patch_expectation_count_window(dx, dy, float(rob.m.sigma), "mu")
                    patch_mu1 = _patch_expectation_count_window(dx, dy, float(rob.m.sigma), "lam")
                    patch_mu1 = max(patch_mu1, patch_mu0 * 1.05)
                    llr_prev = float(prev_state.get("llr", 0.0)) if prev_state else 0.0
                    llr_incr = float(recent_detection_count) * math.log(max(patch_mu1, 1e-9) / max(patch_mu0, 1e-9)) - (patch_mu1 - patch_mu0)
                    llr = llr_prev + llr_incr
                    best_mode = None
                    best_mode_score = None
                    best_mode_cost = None
                    best_mode_event_prob = None
                    best_mode_deltaJ_per_cost = None
                    for mode in deterring_modes.keys():
                        mode_score = _action_score_deterrence(dx, dy, mode)
                        params = deterring_modes.get(mode, {})
                        mode_cost = _cost_eta(
                            dx,
                            dy,
                            w_eta_override=float(params.get("w_eta", cost_w_eta)),
                            fixed_cost=float(params.get("fixed_cost", 0.0)),
                        )
                        sigma_u = float(params.get("sigma", rob.m.sigma))
                        mode_p_event = _event_probability(dx, dy, sigma_u)
                        mode_deltaJ_per_cost = mode_score / max(mode_cost, 1e-6)
                        if best_mode is None or mode_score > best_mode_score:
                            best_mode = mode
                            best_mode_score = mode_score
                            best_mode_cost = mode_cost
                            best_mode_event_prob = mode_p_event
                            best_mode_deltaJ_per_cost = mode_deltaJ_per_cost
                    self._deterring_cluster_state[ck] = {
                        "count": int(persistence),
                        "last_t": float(now_t),
                        "support": int(support),
                        "llr": float(llr),
                        "last_count_window_start_t": float(now_t - count_window_s),
                        "recent_detection_count": int(recent_detection_count),
                        "patch_mu0": float(patch_mu0),
                        "patch_mu1": float(patch_mu1),
                        "p_event": float(best_mode_event_prob or 0.0),
                        "deltaJ_per_cost": float(best_mode_deltaJ_per_cost or 0.0),
                    }
                    self.diag_counts["model_deterring_llr_sum"] += float(llr)
                    self.diag_counts["model_deterring_llr_samples"] += 1
                    self.diag_counts["model_deterring_llr_max"] = max(
                        float(self.diag_counts.get("model_deterring_llr_max", float("-inf"))),
                        float(llr),
                    )
                    self.diag_counts["model_deterring_p_event_sum"] += float(best_mode_event_prob or 0.0)
                    self.diag_counts["model_deterring_p_event_samples"] += 1
                    self.diag_counts["model_deterring_deltaJ_per_cost_sum"] += float(best_mode_deltaJ_per_cost or 0.0)
                    self.diag_counts["model_deterring_deltaJ_per_cost_samples"] += 1
                    if best_mode is not None:
                        candidates.append({
                            "type": "deterring",
                            "x": float(dx),
                            "y": float(dy),
                            "origin": "model_detection_cluster",
                            "mode": best_mode,
                            "support": int(support),
                            "persistence": int(persistence),
                            "risk_conf": float(_risk_confidence(dx, dy)),
                            "eta_s": _eta_seconds(dx, dy),
                            "cluster_key": ck,
                            "predicted_deltaJ": float(best_mode_score),
                            "llr": float(llr),
                            "recent_detection_count": int(recent_detection_count),
                            "patch_mu0": float(patch_mu0),
                            "patch_mu1": float(patch_mu1),
                            "p_event": float(best_mode_event_prob or 0.0),
                            "deltaJ_per_cost": float(best_mode_deltaJ_per_cost or 0.0),
                            "cost_eta": float(best_mode_cost or 0.0),
                        })

                # Cleanup stale cluster state for this robot.
                stale = [
                    key for key, st in self._deterring_cluster_state.items()
                    if (key[0] == rid) and ((float(now_t) - float(st.get("last_t", -1e9))) > 3.0 * persist_gap_s)
                ]
                for key in stale:
                    self._deterring_cluster_state.pop(key, None)
                    self._last_model_deterring_fire.pop(key, None)

            # Cooldown gate for patrols per robot
            next_ok = self._next_allowed.get(rid, -1e9)
            if now_t < next_ok and enable_model_scored_deterring:
                self.diag_counts["model_deterring_rejected_cooldown"] += int(len(deterring_points))
            if now_t >= next_ok and candidates:
                best = None
                best_patrol = None
                det_eligible = 0
                for cand in candidates:
                    ttype = str(cand["type"]).strip().lower()
                    x = float(cand["x"])
                    y = float(cand["y"])
                    if ttype == "deterring":
                        self.diag_counts["model_deterring_candidates_total"] += 1
                        pred_dj = float(cand.get("predicted_deltaJ", _action_score_deterrence(x, y, cand.get("mode"))))
                        if gate_policy == "sprt_capacity":
                            ck = cand.get("cluster_key")
                            if ck is not None:
                                cluster_state = self._deterring_cluster_state.get(ck, {})
                                llr_val = float(cluster_state.get("llr", cand.get("llr", 0.0)))
                            else:
                                llr_val = float(cand.get("llr", 0.0))
                            if llr_val <= sprt_reject:
                                self.diag_counts["model_deterring_rejected_sprt_negative"] += 1
                                if ck is not None and ck in self._deterring_cluster_state:
                                    self._deterring_cluster_state[ck]["llr"] = 0.0
                                continue
                            if llr_val < sprt_accept:
                                self.diag_counts["model_deterring_rejected_sprt_pending"] += 1
                                continue
                            self.diag_counts["model_deterring_pass_sprt"] += 1

                            p_event = float(cand.get("p_event", 0.0))
                            if p_event < chance_threshold:
                                self.diag_counts["model_deterring_rejected_chance"] += 1
                                continue
                            self.diag_counts["model_deterring_pass_chance"] += 1

                            if pred_dj <= 0.0 or pred_dj < float(min_predicted_deltaJ_for_model_deterring):
                                self.diag_counts["model_deterring_rejected_predicted_deltaJ"] += 1
                                continue
                            self.diag_counts["model_deterring_pass_predicted_deltaJ"] += 1

                            dj_per_cost = float(cand.get("deltaJ_per_cost", 0.0))
                            if dj_per_cost < min_deltaJ_per_cost:
                                self.diag_counts["model_deterring_rejected_utility_ratio"] += 1
                                continue
                            self.diag_counts["model_deterring_pass_utility_ratio"] += 1

                            cap_ready = bool(preventive_capacity_ready_by_robot.get(rid, False))
                            if cap_ready:
                                remaining = float(preventive_capacity_remaining_by_robot.get(rid, 0.0))
                                if remaining < 1.0:
                                    self.diag_counts["model_deterring_rejected_capacity"] += 1
                                    continue
                                self.diag_counts["model_deterring_pass_capacity"] += 1
                        else:
                            if pred_dj < float(min_predicted_deltaJ_for_model_deterring):
                                self.diag_counts["model_deterring_rejected_predicted_deltaJ"] += 1
                                continue
                            self.diag_counts["model_deterring_pass_predicted_deltaJ"] += 1
                        field_val = _field_score(x, y)
                        if ttype == "patrolling":
                            if field_val < min_hotspot_score:
                                continue
                        else:
                            if (deterring_field_threshold is not None) and (field_val < float(deterring_field_threshold)):
                                self.diag_counts["model_deterring_rejected_field"] += 1
                                continue
                            self.diag_counts["model_deterring_pass_field"] += 1
                    if ttype == "deterring":
                        if gate_policy == "heuristic":
                            conf = float(cand.get("risk_conf", _risk_confidence(x, y)))
                            if conf < float(deterring_risk_threshold):
                                self.diag_counts["model_deterring_rejected_risk"] += 1
                                continue
                            self.diag_counts["model_deterring_pass_risk"] += 1
                            if int(cand.get("persistence", 0)) < persist_min:
                                self.diag_counts["model_deterring_rejected_persistence"] += 1
                                continue
                            if int(cand.get("support", 0)) < int(deterring_min_recent_points):
                                self.diag_counts["model_deterring_rejected_support"] += 1
                                continue
                            self.diag_counts["model_deterring_pass_support"] += 1
                        if rid in busy_deterring_robots:
                            cand_support = int(cand.get("support", 0))
                            cand_conf = float(cand.get("risk_conf", 0.0))
                            if (cand_support < busy_support_override) and (cand_conf < busy_risk_override):
                                self.diag_counts["model_deterring_rejected_busy"] += 1
                                continue
                        if float(cand.get("eta_s", float("inf"))) > max_eta_s:
                            self.diag_counts["model_deterring_rejected_eta"] += 1
                            continue
                        ck = cand.get("cluster_key")
                        if repeat_block_window > 0.0:
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
                            last_fire = self._last_model_deterring_fire.get(ck, None) if ck is not None else None
                            if (not has_recent_det) and (last_fire is not None):
                                has_recent_det = (float(now_t) - float(last_fire.get("t", -1e9))) <= repeat_block_window
                            if has_recent_det:
                                prev_support = int(last_fire.get("support", 0)) if last_fire is not None else 0
                                if int(cand.get("support", 0)) <= prev_support:
                                    self.diag_counts["model_deterring_rejected_repeat_no_new_support"] += 1
                                    continue

                        score = _action_score_deterrence(x, y, cand["mode"])
                        det_eligible += 1
                    else:
                        score = _action_score_patrol(x, y)
                    cand_scored = dict(cand)
                    cand_scored["score"] = float(score)
                    if best is None or float(score) > float(best["score"]):
                        best = cand_scored
                    if ttype == "patrolling":
                        if best_patrol is None or float(score) > float(best_patrol["score"]):
                            best_patrol = cand_scored

                if best is not None and str(best.get("type", "")).strip().lower() == "deterring" and best_patrol is not None:
                    if gate_policy == "sprt_capacity":
                        patrol_ref = max(0.0, float(best_patrol["score"]))
                        if float(best.get("predicted_deltaJ", best["score"])) <= patrol_ref * (1.0 + score_margin):
                            self.diag_counts["model_deterring_rejected_margin"] += 1
                            best = best_patrol
                    else:
                        if float(best["score"]) <= float(best_patrol["score"]) + score_margin:
                            self.diag_counts["model_deterring_rejected_margin"] += 1
                            best = best_patrol

                if best is not None:
                    _score = float(best["score"])
                    ttype = str(best["type"]).strip().lower()
                    x = float(best["x"])
                    y = float(best["y"])
                    origin = str(best.get("origin", "unknown"))
                    mode = best.get("mode")
                    support = int(best.get("support", 0))
                    jx = (random.uniform(-1,1) * jitter_m) if ttype == "patrolling" else 0.0
                    jy = (random.uniform(-1,1) * jitter_m) if ttype == "patrolling" else 0.0
                    self._add({
                        'robot_id': rid,
                        'type': ttype,
                        'x': float(x + jx), 'y': float(y + jy),
                        'time': float(now_t),
                        'origin': origin,
                        'mode': mode,
                        'score': float(_score),
                        'support': int(support),
                        'risk_conf': float(best.get("risk_conf", 0.0)),
                        'eta_s': float(best.get("eta_s", 0.0)),
                        'persistence': int(best.get("persistence", 0)),
                        'predicted_deltaJ': float(best.get("predicted_deltaJ", _score if ttype == "deterring" else 0.0)),
                        'p_event': float(best.get("p_event", 0.0)),
                        'deltaJ_per_cost': float(best.get("deltaJ_per_cost", 0.0)),
                        'llr': float(best.get("llr", 0.0)),
                    })
                    if ttype == "deterring":
                        self.diag_counts["model_deterring_generated"] += 1
                        ck = best.get("cluster_key")
                        if ck is not None:
                            self._last_model_deterring_fire[ck] = {
                                "t": float(now_t),
                                "support": int(support),
                            }
                    elif det_eligible > 0:
                        self.diag_counts["model_deterring_not_selected"] += int(det_eligible)
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
            return
        self._keys.add(key)
        self._rows.append({
            'robot_id': task['robot_id'],
            'type': task['type'],                         # 'deterring' or 'patrolling'
            'x': float(task['x']),
            'y': float(task['y']),
            'time': float(task['time']),
            'origin': task.get('origin', 'unknown'),      # 'detection'|'hotspot'|'fallback'
            'mode': task.get('mode'),
            'score': float(task.get('score', 0.0)),
            # Utility proxy used by lab assignment/queue discipline.
            'utility': float(task.get('utility', task.get('score', 0.0))),
            'support': int(task.get('support', 0)),
            'risk_conf': float(task.get('risk_conf', 0.0)),
            'eta_s': float(task.get('eta_s', 0.0)),
            'persistence': int(task.get('persistence', 0)),
            'predicted_deltaJ': float(task.get('predicted_deltaJ', 0.0)),
            'p_event': float(task.get('p_event', 0.0)),
            'deltaJ_per_cost': float(task.get('deltaJ_per_cost', 0.0)),
            'llr': float(task.get('llr', 0.0)),
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
            "w_load":  0.8,   # active task load penalty
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

    def set_load(self, load_by_robot: dict[str, int]):
        self.load_by_robot = {str(k): int(v) for k, v in (load_by_robot or {}).items()}

    def candidate_robot_ids(self, task: dict) -> tuple[list[str], str]:
        """
        Returns eligible candidate robots plus scope label using the same policy
        as assign_task().
        """
        owner = task.get("robot_id")
        if task.get("type") == "deterring":
            eligible = [rid for rid in self.P if self._eligible(self.P[rid], task)]
            return eligible, "global_deterring"

        local_pool = []
        if owner in self.R:
            local_pool.append(owner)
            local_pool.extend([rid for rid in self.R[owner].neighbors if rid not in local_pool])
        eligible = [rid for rid in local_pool if rid in self.P and self._eligible(self.P[rid], task)]
        if eligible:
            return eligible, "local"
        eligible = [rid for rid in self.P if self._eligible(self.P[rid], task)]
        return eligible, "global_fallback"

    def eligible_robot_ids(self, task: dict) -> list[str]:
        """Global eligible set (ignores locality-first preference for patrol)."""
        return [rid for rid in self.P if self._eligible(self.P[rid], task)]

    def score_robot_for_task(self, robot_id: str, task: dict) -> float:
        prof = self.P.get(robot_id)
        if prof is None:
            return float("-inf")
        if not self._eligible(prof, task):
            return float("-inf")
        return float(self._score(prof, task))

    def select_secondary_for_deterring(self, primary: str, scored: list[tuple[float, str]], task: dict) -> str | None:
        """
        Shared secondary-selection policy for deterring tasks.
        """
        if task.get("type") != "deterring" or len(scored) <= 1:
            return None
        for _, rid in scored[1:]:
            if self.P[primary].type == "UAV" and self.P[rid].type == "UGV":
                return rid
        return scored[1][1]

    # ---------- public API ----------
    def assign_task(self, task: dict) -> dict | None:
        """
        Returns an assignment dict:
          {task: <task>, primary: <robot_id>, secondary: <robot_id or None>, details: {...}}
        or None if no eligible robot.
        """
        eligible, scope = self.candidate_robot_ids(task)
        if not eligible:
            return None

        scored = [(self._score(self.P[rid], task), rid) for rid in eligible]
        scored.sort(reverse=True, key=lambda x: x[0])
        primary = scored[0][1]

        secondary = self.select_secondary_for_deterring(primary, scored, task)

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
        rx, ry = _robot_pose_guess(rob)
        dist = math.hypot(task["x"] - rx, task["y"] - ry)

        spin = w["uav_spinup_s"] if prof.type == "UAV" else w["ugv_spinup_s"]
        eta = dist / max(prof.speed_mps, 1e-6) + spin

        cap = prof.deterrent_eff if task["type"] == "deterring" else 1.0
        zone_bonus = 1.0 if point_in_polygon(task["x"], task["y"], rob.zone_polygon) else 0.0
        load = float(self.load_by_robot.get(prof.id, 0))

        return (w["w_cap"]   * cap
              - w["w_eta"]   * eta
              + w["w_stay"]  * prof.endurance_min
              + w["w_zone"]  * zone_bonus
              + w["w_health"]* prof.health
              + w["w_prio"]  * prio
              - w["w_load"]  * load)

def _robot_pose_guess(rob: "Robot") -> tuple[float,float]:
    """
    If you don't track live robot poses yet, use the zone centroid as a proxy.
    Replace with your real (x,y) when available.
    """
    cx, cy = polygon_centroid(rob.zone_polygon)
    return float(cx), float(cy)
