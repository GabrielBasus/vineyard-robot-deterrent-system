from __future__ import annotations

import math
from typing import List

import numpy as np

from habituation_stl.mission_spec import SpecParams
from habituation_stl.task_value import CellState, Dynamics, counterfactual_value
from ZonePartitioner import Point, point_in_polygon, point_to_poly_distance, polygon_centroid


def _time_integral_factor(decay_s: float, horizon_s: float) -> float:
    """Return the finite-horizon integral of an exponential decay process."""
    decay_s = max(float(decay_s), 1e-9)
    horizon_s = max(float(horizon_s), 0.0)
    return float(decay_s * (1.0 - math.exp(-horizon_s / decay_s)))


def _normalized_gaussian_kernel(dx: float, dy: float, sigma: float) -> tuple[int, np.ndarray]:
    """Evaluate a normalized spatial Gaussian kernel for counterfactual suppression."""
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
    """Approximate Eq. (5) with a local grid patch and capped suppression."""
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
        "suppression_amplitude": float(suppression_amp),
        "suppression_integral_factor": float(suppress_factor),
        "footprint_radius_cells": int(footprint_rad),
        "footprint_kernel_sum": float(np.sum(footprint_kernel)),
        "grid_cell_area_m2": float(delta_a),
        "available_integral_total": float(np.sum(available_integral_grid)),
        "available_integral_positive_cells": int(np.count_nonzero(available_integral_grid > 0.0)),
    }


def estimate_patrol_response_reduction(
    model,
    x: float,
    y: float,
    *,
    horizon_s: float,
    detect_range_m: float,
    detect_prob_per_step: float,
    detection_dwell_s: float,
    followup_success_prob: float,
    response_eta_decay_s: float,
    followup_speed_mps: float,
    detect_sigma_m: float | None = None,
    mask_poly=None,
    weight_fn=None,
    value_edge_gain: float = 0.5,
    value_edge_scale: float = 30.0,
    value_block_gain: float = 0.3,
    value_block_size: float = 80.0,
    baseline_grid: np.ndarray | None = None,
    available_integral_grid: np.ndarray | None = None,
) -> dict:
    """Approximate patrol-side exposure reduction from observation coverage and follow-up response."""
    if baseline_grid is None:
        baseline_grid = model.mu * model.time_multiplier(model.t_now)
    if available_integral_grid is None:
        risk_factor = _time_integral_factor(model.omega, horizon_s)
        available_integral_grid = np.clip(model.lam - baseline_grid, 0.0, None) * risk_factor

    detect_range = max(float(detect_range_m), 1.0e-9)
    detect_sigma = (
        max(float(detect_sigma_m), 1.0e-9)
        if detect_sigma_m is not None
        else max(0.5 * detect_range, max(float(model.dx), float(model.dy), 1.0e-9))
    )
    detect_prob = min(max(float(detect_prob_per_step), 0.0), 1.0)
    dwell_s = max(float(detection_dwell_s), 1.0e-9)
    followup_success = min(max(float(followup_success_prob), 0.0), 1.0)
    response_decay = max(float(response_eta_decay_s), 1.0e-9)
    followup_speed = max(float(followup_speed_mps), 1.0e-9)

    detect_prob_effective = 1.0 - math.exp(-detect_prob * dwell_s)
    response_scale = detect_prob_effective * followup_success
    detect_r2 = detect_range ** 2
    sigma2 = max(detect_sigma ** 2, 1.0e-9)

    grid_step = max(float(model.dx), float(model.dy), 1.0e-9)
    rad = int(math.ceil(detect_range / grid_step))
    iy, ix = model.world_to_idx(x, y)
    y0 = max(0, iy - rad)
    y1 = min(model.ny, iy + rad + 1)
    x0 = max(0, ix - rad)
    x1 = min(model.nx, ix + rad + 1)

    delta_a = float(model.dx * model.dy)
    weighted_capture_sum = 0.0
    coverage_kernel_mass = 0.0
    contributing_cells = 0

    for yy in range(y0, y1):
        wy = float(model.ys[yy])
        for xx in range(x0, x1):
            wx = float(model.xs[xx])
            if (mask_poly is not None) and (not point_in_polygon(wx, wy, mask_poly)):
                continue

            dxw = wx - float(x)
            dyw = wy - float(y)
            dist2 = dxw * dxw + dyw * dyw
            if dist2 > detect_r2:
                continue

            available_here = float(available_integral_grid[yy, xx])
            if available_here <= 0.0:
                continue

            kernel_raw = math.exp(-0.5 * dist2 / sigma2)
            if kernel_raw <= 0.0:
                continue

            if weight_fn is not None:
                weight = float(weight_fn(wx, wy))
            else:
                dist_edge = point_to_poly_distance((wx, wy), mask_poly) if mask_poly else 0.0
                edge_w = float(value_edge_gain) * math.exp(-dist_edge / max(float(value_edge_scale), 1.0e-9))
                bx = math.sin(2.0 * math.pi * wx / max(float(value_block_size), 1.0e-9))
                by = math.sin(2.0 * math.pi * wy / max(float(value_block_size), 1.0e-9))
                block_w = float(value_block_gain) * (0.5 + 0.5 * bx * by)
                weight = 1.0 + edge_w + block_w
            if weight <= 0.0:
                continue

            eta_followup = math.hypot(dxw, dyw) / followup_speed
            eta_factor = math.exp(-eta_followup / response_decay)
            if eta_factor <= 0.0:
                continue

            weighted_capture_sum += weight * available_here * kernel_raw * eta_factor * delta_a
            coverage_kernel_mass += kernel_raw
            contributing_cells += 1

    predicted_reduction_raw = 0.0
    if coverage_kernel_mass > 0.0 and response_scale > 0.0:
        predicted_reduction_raw = max(
            0.0,
            response_scale * weighted_capture_sum / max(math.sqrt(coverage_kernel_mass), 1.0e-6),
        )

    return {
        "predicted_reduction_raw": float(predicted_reduction_raw),
        "weighted_capture_sum": float(weighted_capture_sum),
        "coverage_kernel_mass": float(coverage_kernel_mass),
        "contributing_cells": int(contributing_cells),
        "effective_detect_prob": float(detect_prob_effective),
        "response_scale": float(response_scale),
        "detection_range_m": float(detect_range),
        "detection_sigma_m": float(detect_sigma),
        "response_eta_decay_s": float(response_decay),
        "grid_cell_area_m2": float(delta_a),
        "available_integral_total": float(np.sum(available_integral_grid)),
        "available_integral_positive_cells": int(np.count_nonzero(available_integral_grid > 0.0)),
    }


def cell_exposure_rate(
    model,
    cell_poly,
    *,
    weight_fn=None,
    field_grid: np.ndarray | None = None,
) -> float:
    """Integrate value-weighted SESTPP intensity over one partition cell.

    This is the adapter for proposal signal e_z = integral_Z w(x) lambda_hat(x,t) dx.
    """
    if not cell_poly:
        return 0.0
    field = model.lam if field_grid is None else field_grid
    if field is None:
        return 0.0

    xs_poly = [float(p[0]) for p in cell_poly]
    ys_poly = [float(p[1]) for p in cell_poly]
    min_x, max_x = min(xs_poly), max(xs_poly)
    min_y, max_y = min(ys_poly), max(ys_poly)
    ix0 = max(0, int(np.searchsorted(model.xs, min_x, side="left") - 1))
    ix1 = min(model.nx - 1, int(np.searchsorted(model.xs, max_x, side="right")))
    iy0 = max(0, int(np.searchsorted(model.ys, min_y, side="left") - 1))
    iy1 = min(model.ny - 1, int(np.searchsorted(model.ys, max_y, side="right")))

    delta_a = float(model.dx * model.dy)
    total = 0.0
    for yy in range(iy0, iy1 + 1):
        wy = float(model.ys[yy])
        for xx in range(ix0, ix1 + 1):
            wx = float(model.xs[xx])
            if not point_in_polygon(wx, wy, cell_poly):
                continue
            weight = float(weight_fn(wx, wy)) if weight_fn is not None else 1.0
            if weight <= 0.0:
                continue
            total += weight * float(field[yy, xx]) * delta_a
    return float(max(total, 0.0))


def estimate_stl_counterfactual_value(
    model,
    x: float,
    y: float,
    *,
    mode,
    mode_to_id: dict,
    hab,
    spec_params: SpecParams,
    dynamics: Dynamics,
    cell_polys,
    local_cell_ids,
    last_service_t_by_cell: dict,
    now_t: float,
    completion_lead_s: float,
    weight_fn=None,
    target_cell_id: int | None = None,
) -> dict:
    """Compute proposal U(a,r) for one candidate deterrence action.

    Returns compatibility diagnostics so the existing task rows can continue to
    expose predicted_deltaJ/deltaJ_per_cost while the underlying value is STL
    robustness margin.
    """
    if hab is None or spec_params is None or dynamics is None:
        return {
            "predictive_stl_U": 0.0,
            "stl_available": False,
            "stl_reason": "missing_stl_context",
        }
    if not cell_polys:
        return {
            "predictive_stl_U": 0.0,
            "stl_available": False,
            "stl_reason": "missing_cells",
        }

    if target_cell_id is None:
        for cid, poly in enumerate(cell_polys):
            if poly and point_in_polygon(float(x), float(y), poly):
                target_cell_id = int(cid)
                break
    if target_cell_id is None:
        return {
            "predictive_stl_U": 0.0,
            "stl_available": False,
            "stl_reason": "target_outside_cells",
        }

    mode_key = str(mode)
    mode_id = mode_to_id.get(mode_key)
    if mode_id is None:
        mode_id = mode_to_id.get(mode)
    if mode_id is None:
        return {
            "predictive_stl_U": 0.0,
            "stl_available": False,
            "stl_reason": "unknown_mode",
            "stl_target_cell": int(target_cell_id),
        }

    cells = [int(c) for c in (local_cell_ids or []) if c is not None]
    if int(target_cell_id) not in cells:
        cells.append(int(target_cell_id))
    cells = sorted({int(c) for c in cells if 0 <= int(c) < len(cell_polys)})
    if not cells:
        return {
            "predictive_stl_U": 0.0,
            "stl_available": False,
            "stl_reason": "empty_local_cells",
            "stl_target_cell": int(target_cell_id),
            "stl_mode_id": int(mode_id),
        }

    try:
        if "hab" in set(str(clause) for clause in spec_params.active_clauses):
            stl_eta_at_apply = float(hab.effectiveness(int(target_cell_id), int(mode_id)))
        else:
            stl_eta_at_apply = 1.0
    except Exception:
        stl_eta_at_apply = float("nan")

    states = {}
    for cid in cells:
        e0 = cell_exposure_rate(model, cell_polys[cid], weight_fn=weight_fn)
        last_t = float(last_service_t_by_cell.get(cid, 0.0))
        g0 = max(0.0, float(now_t) - last_t)
        states[int(cid)] = CellState(e0=float(e0), g0=float(g0))

    u_value = counterfactual_value(
        (int(target_cell_id), int(mode_id), float(completion_lead_s)),
        cells,
        states,
        hab,
        spec_params,
        dynamics,
    )
    return {
        "predictive_stl_U": float(u_value),
        "stl_available": True,
        "stl_reason": None,
        "stl_target_cell": int(target_cell_id),
        "stl_mode_id": int(mode_id),
        "stl_eta_at_apply": float(stl_eta_at_apply),
        "stl_local_cell_count": int(len(cells)),
        "stl_completion_lead_s": float(completion_lead_s),
        "stl_target_exposure_rate": float(states[int(target_cell_id)].e0),
        "stl_target_coverage_age_s": float(states[int(target_cell_id)].g0),
    }


def cluster_points(points: List[Point], radius: float) -> List[Point]:
    """Cluster nearby detections or hotspot samples into representative task locations."""
    pts = points[:]
    out = []
    while pts:
        p = pts.pop()
        cluster = [p]
        rest = []
        for q in pts:
            if (p[0] - q[0]) ** 2 + (p[1] - q[1]) ** 2 <= radius ** 2:
                cluster.append(q)
            else:
                rest.append(q)
        pts = rest
        xs = [c[0] for c in cluster]
        ys = [c[1] for c in cluster]
        out.append((sum(xs) / len(xs), sum(ys) / len(ys)))
    return out


def _robot_pose_guess(rob: "Robot", robot_pose: tuple[float, float] | None = None) -> tuple[float, float]:
    """Use the live pose when available, else fall back to the zone centroid."""
    if robot_pose is not None:
        return float(robot_pose[0]), float(robot_pose[1])
    cx, cy = polygon_centroid(rob.zone_polygon)
    return float(cx), float(cy)
