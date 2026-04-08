from __future__ import annotations

import math
from typing import Dict, List, Optional, Tuple

import matplotlib.pyplot as plt
import numpy as np
import ZonePartitioner as zp

from tracking_export import summarize_ndarray


DEFAULT_INTERVENTION_MODE = "default"


class OnlineSESTPP:
    """Grid-based online SESTPP with persistent mode-aware inhibition.

    `trigger_mass` stores self- and cross-excitation and decays with the
    shared trigger constant `omega`.

    `inhib_channels` stores one inhibition grid per intervention mode. Each
    channel keeps its own `omega_inhib`, so deterrence modes can retain
    suppression for different lengths of time.

    `inhib_mass` is the derived total inhibitory field retained for backward
    compatibility. It is always the sum of all per-mode channels, so the
    intensity update remains:

        lam = clip(mu * time_multiplier + trigger_mass - inhib_mass, 0, None)
    """

    def __init__(self, x_min, x_max, y_min, y_max, nx, ny,
                 sigma=15.0, omega=600.0, omega_inhib=600.0,
                 alpha_in=0.25, alpha_cross=0.10, alpha_inhib=0.20,
                 mu_base=1e-4, bg_ema=1e-6):
        self.nx, self.ny = nx, ny
        self.x_min, self.x_max = x_min, x_max
        self.y_min, self.y_max = y_min, y_max
        self.dx = (x_max - x_min) / (nx - 1)
        self.dy = (y_max - y_min) / (ny - 1)
        self.sigma = float(sigma)
        self.omega = float(omega)
        self.omega_inhib = float(omega_inhib)
        self.alpha_in = float(alpha_in)
        self.alpha_cross = float(alpha_cross)
        self.alpha_inhib = float(alpha_inhib)
        self.mu = np.full((ny, nx), mu_base, float)
        self.trigger_mass = np.zeros((ny, nx), float)
        self.inhib_channels: Dict[str, np.ndarray] = {}
        self.inhib_channel_omegas: Dict[str, float] = {}
        self.default_intervention_mode = DEFAULT_INTERVENTION_MODE
        self.inhib_mass = np.zeros((ny, nx), float)
        self.lam = np.full((ny, nx), mu_base, float)
        self.bg_ema = float(bg_ema)
        self.t_now = 0.0
        self._build_coords()
        self._rebuild_kernel()

    def _build_coords(self):
        self.xs = np.linspace(self.x_min, self.x_max, self.nx)
        self.ys = np.linspace(self.y_min, self.y_max, self.ny)

    def _build_kernel(self, sigma: float) -> Tuple[int, np.ndarray]:
        sigma = max(float(sigma), 1e-9)
        rad = int(math.ceil(3 * sigma / max(self.dx, self.dy)))
        kx = np.arange(-rad, rad + 1)
        ky = np.arange(-rad, rad + 1)
        KX, KY = np.meshgrid(kx, ky, indexing='xy')
        KDX = KX * self.dx
        KDY = KY * self.dy
        dist2 = KDX**2 + KDY**2
        G = np.exp(-0.5 * dist2 / (sigma**2))
        s = G.sum()
        return rad, G / (s if s > 0 else 1.0)

    def _rebuild_kernel(self):
        self.k_rad, self.G = self._build_kernel(self.sigma)

    def set_params(self, alpha_in=None, alpha_cross=None, alpha_inhib=None,
                   sigma=None, omega=None, omega_inhib=None, bg_ema=None):
        if alpha_in is not None:
            self.alpha_in = float(alpha_in)
        if alpha_cross is not None:
            self.alpha_cross = float(alpha_cross)
        if alpha_inhib is not None:
            self.alpha_inhib = float(alpha_inhib)
        if sigma is not None:
            self.sigma = float(sigma)
            self._rebuild_kernel()
        if omega is not None:
            self.omega = float(omega)
        if omega_inhib is not None:
            self.omega_inhib = float(omega_inhib)
            if self.default_intervention_mode in self.inhib_channel_omegas:
                self.inhib_channel_omegas[self.default_intervention_mode] = self.omega_inhib
        if bg_ema is not None:
            self.bg_ema = float(bg_ema)

    def time_multiplier(self, t: float) -> float:
        day = 24 * 3600.0
        phi = 2 * math.pi * (t % day) / day
        a1, a2 = 0.4, 0.15
        mult = 1.0 + a1 * math.sin(phi) + a2 * math.sin(2 * phi)
        return max(0.2, mult)

    def world_to_idx(self, x, y) -> Tuple[int, int]:
        ix = int(round((x - self.x_min) / (self.x_max - self.x_min) * (self.nx - 1)))
        iy = int(round((y - self.y_min) / (self.y_max - self.y_min) * (self.ny - 1)))
        ix = max(0, min(self.nx - 1, ix))
        iy = max(0, min(self.ny - 1, iy))
        return iy, ix

    @property
    def total_inhib_mass(self) -> np.ndarray:
        """Derived total inhibitory mass across all intervention modes."""
        return self.inhib_mass

    def _canonical_intervention_mode(self, mode: Optional[str]) -> str:
        if mode is None:
            return self.default_intervention_mode
        mode = str(mode).strip()
        return mode if mode else self.default_intervention_mode

    def _ensure_inhib_channel(self, mode: Optional[str], omega_inhib: Optional[float] = None):
        mode_key = self._canonical_intervention_mode(mode)
        if mode_key not in self.inhib_channels:
            self.inhib_channels[mode_key] = np.zeros((self.ny, self.nx), float)
            self.inhib_channel_omegas[mode_key] = float(
                self.omega_inhib if omega_inhib is None else omega_inhib
            )
        elif omega_inhib is not None:
            self.inhib_channel_omegas[mode_key] = float(omega_inhib)
        return mode_key, self.inhib_channels[mode_key]

    def _refresh_inhib_mass(self):
        self.inhib_mass.fill(0.0)
        for grid in self.inhib_channels.values():
            self.inhib_mass += grid

    def _update_lambda(self):
        self._refresh_inhib_mass()
        self.lam = np.clip(
            self.mu * self.time_multiplier(self.t_now) + self.trigger_mass - self.inhib_mass,
            0.0,
            None,
        )

    def advance_time(self, dt: float):
        """Advance model time and decay trigger and inhibition state."""
        if dt <= 0:
            return
        self.trigger_mass *= math.exp(-dt / max(self.omega, 1e-9))
        for mode_key, grid in self.inhib_channels.items():
            omega_mode = max(self.inhib_channel_omegas.get(mode_key, self.omega_inhib), 1e-9)
            grid *= math.exp(-dt / omega_mode)
        self.t_now += dt
        self._update_lambda()

    def _stamp(self, x, y, amp: float):
        self._stamp_to(self.trigger_mass, x, y, amp)

    def _stamp_to(self, grid, x, y, amp: float, sigma: Optional[float] = None):
        if sigma is None:
            k_rad, kernel = self.k_rad, self.G
        else:
            k_rad, kernel = self._build_kernel(sigma)
        iy, ix = self.world_to_idx(x, y)
        y0 = max(0, iy - k_rad)
        y1 = min(self.ny, iy + k_rad + 1)
        x0 = max(0, ix - k_rad)
        x1 = min(self.nx, ix + k_rad + 1)
        ky0 = y0 - (iy - k_rad)
        ky1 = ky0 + (y1 - y0)
        kx0 = x0 - (ix - k_rad)
        kx1 = kx0 + (x1 - x0)
        grid[y0:y1, x0:x1] += amp * kernel[ky0:ky1, kx0:kx1]

    def add_local_event(self, x, y):
        """Stamp self-excitation into `trigger_mass` and refresh intensity."""
        self._stamp(x, y, self.alpha_in)
        iy, ix = self.world_to_idx(x, y)
        self.mu[iy, ix] = max(1e-6, (1 - self.bg_ema) * self.mu[iy, ix] + self.bg_ema * self.lam[iy, ix])
        self._update_lambda()

    def add_cross_event(self, x, y, weight=0.35, sigma=None, omega=None):
        """Stamp cross-excitation into `trigger_mass` and refresh intensity."""
        self._stamp_to(self.trigger_mass, x, y, self.alpha_cross * float(weight), sigma=sigma)
        self._update_lambda()

    def add_intervention_event(self, x, y, weight=1.0, sigma=None, omega_inhib=None, *, mode=None):
        """Stamp an intervention into the persistent inhibition channel for `mode`.

        `weight` remains the backward-compatible amplitude multiplier and is the
        natural place to pass thesis-mode suppression strength `beta_u`.

        `sigma` sets the spatial footprint for this stamped intervention.
        `omega_inhib` sets the temporal decay constant for the selected mode
        channel. `mode=None` routes callers to the default compatibility
        channel.
        """
        _, inhib_grid = self._ensure_inhib_channel(mode, omega_inhib=omega_inhib)
        sigma_val = self.sigma if sigma is None else float(sigma)
        self._stamp_to(inhib_grid, x, y, self.alpha_inhib * float(weight), sigma=sigma_val)
        self._update_lambda()

    def hotspots(self, top_k=5, merge_radius=20.0, use_excess=True, mask_poly: Optional[zp.Poly] = None) -> List[Dict]:
        """Return top-k hotspot locations from the current intensity field."""
        field = (self.lam - self.mu) if use_excess else self.lam
        k_short = min(field.size, max(5 * top_k, top_k))
        flat_idx = np.argpartition(field.ravel(), -k_short)[-k_short:]
        flat_sorted = flat_idx[np.argsort(field.ravel()[flat_idx])[::-1]]
        picks = []
        coords = []
        for idx in flat_sorted:
            iy, ix = divmod(idx, self.nx)
            x, y = self.xs[ix], self.ys[iy]
            if mask_poly and (not zp.point_in_polygon(x, y, mask_poly)):
                continue
            if any((x - px) ** 2 + (y - py) ** 2 <= merge_radius ** 2 for (px, py) in coords):
                continue
            coords.append((x, y))
            picks.append({'x': float(x), 'y': float(y), 'score': float(field[iy, ix])})
            if len(picks) >= top_k:
                break
        return picks

    def to_tracking_dict(self, *, include_arrays: bool = False, max_items: int = 50):
        def _array_payload(arr: np.ndarray):
            return np.array(arr, copy=True) if include_arrays else summarize_ndarray(arr)

        channel_items = list(self.inhib_channels.items())[: max(int(max_items), 0)]
        return {
            "x_min": float(self.x_min),
            "x_max": float(self.x_max),
            "y_min": float(self.y_min),
            "y_max": float(self.y_max),
            "nx": int(self.nx),
            "ny": int(self.ny),
            "dx": float(self.dx),
            "dy": float(self.dy),
            "sigma": float(self.sigma),
            "omega": float(self.omega),
            "omega_inhib": float(self.omega_inhib),
            "alpha_in": float(self.alpha_in),
            "alpha_cross": float(self.alpha_cross),
            "alpha_inhib": float(self.alpha_inhib),
            "bg_ema": float(self.bg_ema),
            "t_now": float(self.t_now),
            "default_intervention_mode": str(self.default_intervention_mode),
            "inhib_channel_modes": [str(mode) for mode in self.inhib_channels.keys()],
            "inhib_channel_omegas": {str(k): float(v) for k, v in self.inhib_channel_omegas.items()},
            "mu": _array_payload(self.mu),
            "trigger_mass": _array_payload(self.trigger_mass),
            "inhib_mass": _array_payload(self.inhib_mass),
            "lam": _array_payload(self.lam),
            "xs": _array_payload(self.xs),
            "ys": _array_payload(self.ys),
            "inhib_channels": {
                str(mode): _array_payload(grid)
                for mode, grid in channel_items
            },
            "inhib_channel_count": int(len(self.inhib_channels)),
        }

    def plot_intensity(self):
        plt.imshow(
            self.lam,
            extent=(self.x_min, self.x_max, self.y_min, self.y_max),
            origin='lower',
            cmap='hot',
            interpolation='nearest',
        )
        plt.colorbar(label='Intensity')
        plt.xlabel('X')
        plt.ylabel('Y')
        plt.title('Current Intensity Field')
        plt.show()


if __name__ == "__main__":
    sestpp = OnlineSESTPP(x_min=0, x_max=100, y_min=0, y_max=100, nx=100, ny=100)
    sestpp.add_local_event(50, 50)
    sestpp.advance_time(300)
    sestpp.add_cross_event(60, 60, weight=0.5)
    sestpp.add_intervention_event(55, 55, weight=0.8, sigma=12.0, omega_inhib=900.0, mode="uav_pass")
    sestpp.advance_time(600)
    hotspots = sestpp.hotspots(top_k=3, merge_radius=10.0)
    print("Top hotspots:", hotspots)
    sestpp.plot_intensity()
