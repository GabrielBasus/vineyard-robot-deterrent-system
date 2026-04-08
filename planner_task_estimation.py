from __future__ import annotations

import math
from typing import List

import numpy as np

from ZonePartitioner import Point, point_in_polygon, point_to_poly_distance, polygon_centroid


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


def cluster_points(points: List[Point], radius: float) -> List[Point]:
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
