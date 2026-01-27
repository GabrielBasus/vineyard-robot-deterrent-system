from __future__ import annotations
import math, random
from typing import List, Tuple, Dict, Optional
from collections import deque

import numpy as np
import matplotlib.pyplot as plt
import pandas as pd
import ZonePartitioner as zp
from ZonePartitioner import Point, Poly

# ----------------------------
# Online SESTPP (grid, light)
# ----------------------------

"""
class OnlineSESTPP:
    Implemented using an exponential decay temporal kernel and Gaussian spatial kernel.
    Inputs:
    - Spatial grid defined by (x_min, x_max), (y_min, y_max) and (nx, ny)
    - SESTPP parameters:
        sigma: spatial kernel bandwidth
        omega: temporal decay constant
        alpha_in: self-excitation magnitude
        alpha_cross: cross-excitation magnitude
        mu_base: base background rate
        bg_ema: background rate EMA update factor
    Outputs:
    - lam: current intensity field
    Methods:
    - advance_time(dt): decay trigger mass and update intensity
    - add_local_event(x, y): add self-exciting event at (x, y)
    - add_cross_event(x, y, weight, sigma, omega): add cross-exciting event at (x, y)
    - hotspots(top_k, merge_radius, use_excess, mask_poly): get top-k hotspots
"""
class OnlineSESTPP:
    def __init__(self, x_min, x_max, y_min, y_max, nx, ny,
                 sigma=15.0, omega=600.0, alpha_in=0.25, alpha_cross=0.10,
                 mu_base=1e-4, bg_ema=1e-6):
        self.nx, self.ny = nx, ny
        self.x_min, self.x_max = x_min, x_max
        self.y_min, self.y_max = y_min, y_max
        self.dx = (x_max - x_min) / (nx - 1)
        self.dy = (y_max - y_min) / (ny - 1)
        self.sigma = float(sigma)
        self.omega = float(omega)
        self.alpha_in = float(alpha_in)
        self.alpha_cross = float(alpha_cross)
        self.mu = np.full((ny, nx), mu_base, float)
        self.trigger_mass = np.zeros((ny, nx), float)
        self.lam = np.full((ny, nx), mu_base, float)
        self.bg_ema = float(bg_ema)
        self.t_now = 0.0
        self._build_coords()
        self._rebuild_kernel()

    def _build_coords(self):
        self.xs = np.linspace(self.x_min, self.x_max, self.nx)
        self.ys = np.linspace(self.y_min, self.y_max, self.ny)

    def _rebuild_kernel(self):
        rad = int(math.ceil(3 * self.sigma / max(self.dx, self.dy)))
        self.k_rad = rad
        kx = np.arange(-rad, rad + 1)
        ky = np.arange(-rad, rad + 1)
        KX, KY = np.meshgrid(kx, ky, indexing='xy')
        KDX = KX * self.dx; KDY = KY * self.dy
        dist2 = KDX**2 + KDY**2
        G = np.exp(-0.5 * dist2 / (self.sigma**2))
        s = G.sum(); G = G / (s if s > 0 else 1.0)
        self.G = G

    def set_params(self, alpha_in=None, alpha_cross=None, sigma=None, omega=None, bg_ema=None):
        if alpha_in is not None: self.alpha_in = float(alpha_in)
        if alpha_cross is not None: self.alpha_cross = float(alpha_cross)
        if sigma is not None:
            self.sigma = float(sigma); self._rebuild_kernel()
        if omega is not None: self.omega = float(omega)
        if bg_ema is not None: self.bg_ema = float(bg_ema)

    def time_multiplier(self, t: float) -> float:
        day = 24*3600.0
        phi = 2*math.pi*(t % day)/day
        a1, a2 = 0.4, 0.15
        mult = 1.0 + a1*math.sin(phi) + a2*math.sin(2*phi)
        return max(0.2, mult)

    def world_to_idx(self, x, y) -> Tuple[int, int]:
        ix = int(round((x - self.x_min) / (self.x_max - self.x_min) * (self.nx - 1)))
        iy = int(round((y - self.y_min) / (self.y_max - self.y_min) * (self.ny - 1)))
        ix = max(0, min(self.nx - 1, ix)); iy = max(0, min(self.ny - 1, iy))
        return iy, ix

    def advance_time(self, dt: float):
        if dt <= 0: return
        decay = math.exp(-dt / self.omega)
        self.trigger_mass *= decay
        self.t_now += dt
        self.lam = self.mu * self.time_multiplier(self.t_now) + self.trigger_mass

    def _stamp(self, x, y, amp: float):
        iy, ix = self.world_to_idx(x, y)
        y0 = max(0, iy - self.k_rad); y1 = min(self.ny, iy + self.k_rad + 1)
        x0 = max(0, ix - self.k_rad); x1 = min(self.nx, ix + self.k_rad + 1)
        ky0 = y0 - (iy - self.k_rad); ky1 = ky0 + (y1 - y0)
        kx0 = x0 - (ix - self.k_rad); kx1 = kx0 + (x1 - x0)
        self.trigger_mass[y0:y1, x0:x1] += amp * self.G[ky0:ky1, kx0:kx1]

    def add_local_event(self, x, y):
        self._stamp(x, y, self.alpha_in)
        iy, ix = self.world_to_idx(x, y)
        self.mu[iy, ix] = max(1e-6, (1-self.bg_ema)*self.mu[iy, ix] + self.bg_ema*self.lam[iy, ix])
        self.lam = self.mu * self.time_multiplier(self.t_now) + self.trigger_mass

    def add_cross_event(self, x, y, weight=0.35, sigma=None, omega=None):
        if sigma is not None:
            orig_sigma = self.sigma; self.sigma = float(sigma); self._rebuild_kernel()
        if omega is not None:
            orig_omega = self.omega; self.omega = float(omega)
        self._stamp(x, y, self.alpha_cross * float(weight))
        if sigma is not None:
            self.sigma = orig_sigma; self._rebuild_kernel()
        if omega is not None:
            self.omega = orig_omega
        self.lam = self.mu * self.time_multiplier(self.t_now) + self.trigger_mass

    """
    Get top-k hotspots as list of dicts: {'x': float, 'y': float, 'score': float}
    Inputs:
    - top_k: number of hotspots to return
    - merge_radius: minimum distance between hotspots
    - use_excess: if True, use (lam - mu) as score; else use lam
    - mask_poly: optional polygon to mask hotspots outside area
    Outputs:
    - List of dicts with hotspot info
    """
    def hotspots(self, top_k=5, merge_radius=20.0, use_excess=True, mask_poly: Optional[zp.Poly]=None) -> List[Dict]:
        field = (self.lam - self.mu) if use_excess else self.lam
        k_short = min(field.size, max(5*top_k, top_k))
        flat_idx = np.argpartition(field.ravel(), -k_short)[-k_short:]
        flat_sorted = flat_idx[np.argsort(field.ravel()[flat_idx])[::-1]]
        picks = []; coords = []
        for idx in flat_sorted:
            iy, ix = divmod(idx, self.nx)
            x, y = self.xs[ix], self.ys[iy]
            if mask_poly and (not zp.point_in_polygon(x, y, mask_poly)):  # keep inside zone
                continue
            if any((x-px)**2 + (y-py)**2 <= merge_radius**2 for (px, py) in coords):
                continue
            coords.append((x, y))
            picks.append({'x': float(x), 'y': float(y), 'score': float(field[iy, ix])})
            if len(picks) >= top_k: break
        return picks
    
    def plot_intensity(self):
        plt.imshow(self.lam, extent=(self.x_min, self.x_max, self.y_min, self.y_max),
                   origin='lower', cmap='hot', interpolation='nearest')
        plt.colorbar(label='Intensity')
        plt.xlabel('X'); plt.ylabel('Y')
        plt.title('Current Intensity Field')
        plt.show()

    
if __name__ == "__main__":
    # Example usage
    sestpp = OnlineSESTPP(x_min=0, x_max=100, y_min=0, y_max=100, nx=100, ny=100)
    sestpp.add_local_event(50, 50)
    sestpp.advance_time(300)  # advance 5 minutes
    sestpp.add_cross_event(60, 60, weight=0.5)
    sestpp.advance_time(600)  # advance 10 minutes
    hotspots = sestpp.hotspots(top_k=3, merge_radius=10.0)
    print("Top hotspots:", hotspots)
    sestpp.plot_intensity()