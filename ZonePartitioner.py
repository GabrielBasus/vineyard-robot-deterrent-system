from __future__ import annotations
import math, random
from typing import List, Tuple, Dict, Optional
from collections import deque

import numpy as np
import matplotlib.pyplot as plt
import pandas as pd

# -------------------------------
# Geometry & power diagram utils
# -------------------------------

Point = Tuple[float, float]
Poly  = List[Point]

def clip_polygon_with_halfspace(poly: Poly, a: float, b: float, c: float, eps: float=1e-12) -> Poly:
    if not poly:
        return []
    out: Poly = []
    n = len(poly)
    def side(x, y): return a*x + b*y - c
    for i in range(n):
        x1, y1 = poly[i]
        x2, y2 = poly[(i + 1) % n]
        s1 = side(x1, y1)
        s2 = side(x2, y2)
        in1 = s1 <= eps
        in2 = s2 <= eps
        if in1 and in2:
            out.append((x2, y2))
        elif in1 and not in2:
            out.append(segment_line_intersection((x1,y1),(x2,y2), a,b,c))
        elif (not in1) and in2:
            out.append(segment_line_intersection((x1,y1),(x2,y2), a,b,c))
            out.append((x2, y2))
    return dedup_poly(out, tol=1e-9)

def segment_line_intersection(p1: Point, p2: Point, a: float, b: float, c: float) -> Point:
    x1, y1 = p1; x2, y2 = p2
    dx, dy = x2-x1, y2-y1
    denom = a*dx + b*dy
    t = 0.0 if abs(denom) < 1e-18 else (c - (a*x1 + b*y1)) / denom
    t = max(0.0, min(1.0, t))
    return (x1 + t*dx, y1 + t*dy)

def dedup_poly(poly: Poly, tol: float=1e-9) -> Poly:
    if not poly: return poly
    out = [poly[0]]
    for p in poly[1:]:
        if (p[0]-out[-1][0])**2 + (p[1]-out[-1][1])**2 > tol**2:
            out.append(p)
    if len(out) > 1 and (out[0][0]-out[-1][0])**2 + (out[0][1]-out[-1][1])**2 <= tol**2:
        out.pop()
    return out

def polygon_area(poly: Poly) -> float:
    if not poly: return 0.0
    s = 0.0
    n = len(poly)
    for i in range(n):
        x1,y1 = poly[i]; x2,y2 = poly[(i+1)%n]
        s += x1*y2 - x2*y1
    return 0.5*abs(s)

def polygon_centroid(poly: Poly) -> Point:
    n = len(poly)
    if n == 0: return (float('nan'), float('nan'))
    A = 0.0; Cx = 0.0; Cy = 0.0
    for i in range(n):
        x1,y1 = poly[i]; x2,y2 = poly[(i+1)%n]
        cross = x1*y2 - x2*y1
        A += cross; Cx += (x1 + x2)*cross; Cy += (y1 + y2)*cross
    A *= 0.5
    if abs(A) < 1e-18:
        xs = [p[0] for p in poly]; ys=[p[1] for p in poly]
        return (sum(xs)/n, sum(ys)/n)
    return (Cx/(6*A), Cy/(6*A))

def polygons_touch(poly1: Poly, poly2: Poly, tol: float=1e-6) -> bool:
    if not poly1 or not poly2: return False
    def bbox(poly):
        xs=[p[0] for p in poly]; ys=[p[1] for p in poly]
        return min(xs),min(ys),max(xs),max(ys)
    a1,b1,c1,d1 = bbox(poly1)
    a2,b2,c2,d2 = bbox(poly2)
    if c1 < a2 - tol or c2 < a1 - tol or d1 < b2 - tol or d2 < b1 - tol:
        return False
    if any(point_to_poly_distance(v, poly2) <= tol for v in poly1): return True
    if any(point_to_poly_distance(v, poly1) <= tol for v in poly2): return True
    return False

def point_to_poly_distance(pt: Point, poly: Poly) -> float:
    x,y = pt
    best = float('inf')
    n = len(poly)
    for i in range(n):
        ax,ay = poly[i]; bx,by = poly[(i+1)%n]
        best = min(best, dist_point_to_segment(x,y,ax,ay,bx,by))
    return best

def dist_point_to_segment(px, py, ax, ay, bx, by) -> float:
    abx, aby = bx-ax, by-ay
    apx, apy = px-ax, py-ay
    denom = abx*abx + aby*aby
    if denom <= 1e-18:
        return math.hypot(px-ax, py-ay)
    t = max(0.0, min(1.0, (apx*abx + apy*aby)/denom))
    cx, cy = ax + t*abx, ay + t*aby
    return math.hypot(px-cx, py-cy)

def point_in_polygon(x: float, y: float, poly: Poly) -> bool:
    inside = False
    n = len(poly)
    for i in range(n):
        x1, y1 = poly[i]
        x2, y2 = poly[(i + 1) % n]
        cond = ((y1 > y) != (y2 > y)) and (x < (x2 - x1) * (y - y1) / (y2 - y1 + 1e-12) + x1)
        if cond: inside = not inside
    return inside

def health_to_weight(health: float, mode="direct", scale=800.0, gamma=1.0) -> float:
    h = max(0.0, float(health))
    if mode == "direct":
        return scale * (h**gamma)
    elif mode == "inverse":
        return scale / ((h + 1e-9)**gamma)
    else:
        raise ValueError("mode must be 'direct' or 'inverse'.")

def power_cells(anchors: List[Point], weights: List[float], boundary: Poly) -> List[Poly]:
    n = len(anchors)
    s = [anchors[i][0]**2 + anchors[i][1]**2 - weights[i] for i in range(n)]
    cells: List[Poly] = []
    for i in range(n):
        poly = boundary[:]
        xi, yi = anchors[i]; si = s[i]
        for j in range(n):
            if j == i: continue
            xj, yj = anchors[j]; sj = s[j]
            a = 2.0*(xj - xi)
            b = 2.0*(yj - yi)
            c = sj - si
            poly = clip_polygon_with_halfspace(poly, a, b, c)
            if not poly: break
        cells.append(poly)
    return cells

def build_neighbors(cells: List[Poly], tol: float=1e-3) -> Dict[int, List[int]]:
    n = len(cells)
    nbrs = {i: [] for i in range(n)}
    for i in range(n):
        for j in range(i+1, n):
            if polygons_touch(cells[i], cells[j], tol=tol):
                nbrs[i].append(j)
                nbrs[j].append(i)
    return nbrs

def plot_power_diagram(cells: List[Poly], anchors: List[Point]=[], weights: List[float]=[],
                       ax: Optional[plt.Axes]=None, show=True):
    if ax is None:
        fig, ax = plt.subplots(figsize=(8,8))
    for i, poly in enumerate(cells):
        if not poly: continue
        xs = [p[0] for p in poly] + [poly[0][0]]
        ys = [p[1] for p in poly] + [poly[0][1]]
        ax.plot(xs, ys, 'b-')
        ax.fill(xs, ys, alpha=0.12)
        if anchors:
            cx, cy = polygon_centroid(poly)
            ax.text(cx, cy, str(i), color='red', fontsize=12, ha='center', va='center')
    if anchors:
        for i, (x,y) in enumerate(anchors):
            ax.plot(x, y, 'ro')
            if weights:
                ax.text(x, y, f"{weights[i]:.1f}", color='green', fontsize=8, ha='left', va='bottom')
    ax.set_aspect('equal', 'box')
    if show:
        plt.show()

if __name__ == "__main__":
    # Example usage
    anchors = [(20,30), (80,20), (50,80)]
    weights = [100.0, 200.0, 150.0]
    boundary = [(0,0), (100,0), (100,100), (0,100)]
    cells = power_cells(anchors, weights, boundary)
    plot_power_diagram(cells, anchors, weights)

class ZonePartitioner:
    """
    Maintains health-weighted power diagram cells and neighbor graph.
    Only recomputes when explicitly triggered (e.g., health threshold crossed)
    or when called with force=True.
    """
    def __init__(self, W, H, robots_def, profiles, mode="direct", scale=15000.0, gamma=1.5,
                 partition_types=("UGV",)):
        self.W, self.H = float(W), float(H)
        self.boundary = [(0,0),(W,0),(W,H),(0,H)]
        self.mode, self.scale, self.gamma = mode, float(scale), float(gamma)

        # include only the requested types in the partition
        include = [r["id"] for r in robots_def if profiles[r["id"]].type in partition_types]
        self.ids      = include
        self.anchors  = {rid: tuple(next(rd["anchor"] for rd in robots_def if rd["id"]==rid)) for rid in include}
        self.healths  = {rid: float(next(rd["health"] for rd in robots_def if rd["id"]==rid)) for rid in include}
        self.profiles = profiles  # for health reads if you want to sync

        # Outputs
        self.cells = []
        self.nbrs  = {}

        self.recompute(force=True)

    def recompute(self, force=False):
        anchors = [self.anchors[rid] for rid in self.ids]
        healths = [self.healths[rid] for rid in self.ids]
        weights = [health_to_weight(h, mode=self.mode, scale=self.scale, gamma=self.gamma) for h in healths]
        self.cells = power_cells(anchors, weights, self.boundary)
        self.nbrs  = build_neighbors(self.cells)
        return True

    def update_anchor(self, rid, xy):
        self.anchors[rid] = (float(xy[0]), float(xy[1]))

    def set_health(self, rid, h):
        self.healths[rid] = float(h)

    def maybe_trigger(self, health_threshold=0.25, drop_fraction=0.5, previous_healths=None) -> bool:
        """
        Returns True if a recompute should be triggered:
        - absolute health below threshold, OR
        - relative drop larger than drop_fraction vs previous health snapshot.
        """
        trig = False
        # absolute threshold
        if any(self.healths[rid] <= health_threshold for rid in self.ids):
            trig = True
        # relative drop (optional)
        if previous_healths is not None:
            for rid in self.ids:
                h0 = previous_healths.get(rid, self.healths[rid])
                if h0 > 1e-6 and (self.healths[rid] / h0) <= drop_fraction:
                    trig = True
                    break
        return trig

    def cells_for_ids(self):
        """Return cells in the same order as self.ids (partitioned types only)."""
        return self.cells

    def neighbors_for_id(self, rid):
        # If rid was not included in the partition (e.g., UAV), it has no neighbors.
        if rid not in self.ids:
            return []
        i = self.ids.index(rid)
        return [self.ids[j] for j in self.nbrs.get(i, [])]
