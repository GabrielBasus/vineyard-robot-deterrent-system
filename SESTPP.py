from __future__ import annotations

import math
from dataclasses import dataclass, replace
from typing import Callable, Dict, List, Optional, Tuple

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

    This is the "legacy" estimator. See ``ConsistentOnlineSESTPP`` for the
    estimator whose functional form matches the simulator truth.
    """

    estimator_mode = "legacy"

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

    def _legacy_late_decay(self, t_event: Optional[float], omega: float) -> float:
        """Decay for an event stamped after its own time (delayed relay only).

        ``t_event=None`` (every historical call) returns exactly 1.0. A delayed
        relayed event (EventBus neighbor_delay_s > 0) is stamped with the mass it
        would hold now had it arrived on time: amplitude * exp(-(t_now - t)/omega).
        """
        if t_event is None:
            return 1.0
        lag = float(self.t_now) - float(t_event)
        return math.exp(-lag / max(float(omega), 1e-9)) if lag > 0.0 else 1.0

    def add_cross_event(self, x, y, weight=0.35, sigma=None, omega=None, t: Optional[float] = None):
        """Stamp cross-excitation into `trigger_mass` and refresh intensity.

        ``t`` is passed only for delayed relays (see ``_legacy_late_decay``);
        the trigger mass decays with the model's own ``omega``.
        """
        amp = self.alpha_cross * float(weight)
        if t is not None:
            amp *= self._legacy_late_decay(t, self.omega)
        self._stamp_to(self.trigger_mass, x, y, amp, sigma=sigma)
        self._update_lambda()

    def add_intervention_event(self, x, y, weight=1.0, sigma=None, omega_inhib=None, *, mode=None,
                               t: Optional[float] = None):
        """Stamp an intervention into the persistent inhibition channel for `mode`.

        `weight` remains the backward-compatible amplitude multiplier and is the
        natural place to pass thesis-mode suppression strength `beta_u`.

        `sigma` sets the spatial footprint for this stamped intervention.
        `omega_inhib` sets the temporal decay constant for the selected mode
        channel. `mode=None` routes callers to the default compatibility
        channel.
        """
        mode_key, inhib_grid = self._ensure_inhib_channel(mode, omega_inhib=omega_inhib)
        sigma_val = self.sigma if sigma is None else float(sigma)
        amp = self.alpha_inhib * float(weight)
        if t is not None:
            amp *= self._legacy_late_decay(
                t, self.inhib_channel_omegas.get(mode_key, self.omega_inhib)
            )
        self._stamp_to(inhib_grid, x, y, amp, sigma=sigma_val)
        self._update_lambda()

    def forecast_state(self):
        """Component snapshot for rollout engines (consistent estimator only)."""
        raise NotImplementedError(
            "forecast_state() is defined for estimator_mode='consistent' (ConsistentOnlineSESTPP); "
            "the legacy additive model has no truth-consistent factorisation."
        )

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


# ============================================================================
# Truth-consistent estimator ("consistent" estimator mode)
# ============================================================================

ESTIMATOR_MODES = ("legacy", "consistent")


def canonical_estimator_mode(mode: Optional[str]) -> str:
    """Normalize an estimator-mode label and reject unknown values."""
    key = str(mode or "legacy").strip().lower()
    if key not in ESTIMATOR_MODES:
        raise ValueError(f"estimator_mode must be one of {list(ESTIMATOR_MODES)}, got: {mode!r}")
    return key


@dataclass(frozen=True)
class SuppressionTerm:
    """One completed intervention as seen by the planner model.

    Contributes ``amplitude * exp(-|x - (x, y)|^2 / (2 sigma^2)) * exp(-(t - tau) / omega)``
    to the suppression exponent S_hat(x, t) for t >= tau. ``amplitude`` is
    ``q_hat * beta`` (planner effectiveness just before depletion times the
    planner's per-mode strength), mirroring the truth's ``eta * beta * k * decay``
    term in ``DeterrentSystem._truth_suppression_contributions``.
    """

    x: float
    y: float
    tau: float
    amplitude: float
    sigma: float
    omega: float
    mode: str = "default"
    action_id: Optional[int] = None

    def value(self, x, y, t):
        """Evaluate this term's contribution to S at point(s) (x, y) and time t."""
        dt = float(t) - float(self.tau)
        xa = np.asarray(x, dtype=float)
        ya = np.asarray(y, dtype=float)
        if dt < 0.0:
            return 0.0 * xa
        k = np.exp(-0.5 * ((xa - self.x) ** 2 + (ya - self.y) ** 2) / max(self.sigma ** 2, 1e-9))
        return self.amplitude * k * math.exp(-dt / max(self.omega, 1e-9))


@dataclass
class SESTPPForecastState:
    """Plain, copyable snapshot of a consistent planner model for rollout engines.

    All grids are DENSITIES (events per m^2 per s) on the node grid
    ``ys x xs`` (shape ``(ny, nx)``); multiply by ``dA`` to integrate. The
    intensity factorises exactly as the simulator's truth:

        lam(x, t) = [background(x, t) + excitation(x, t)] * exp(-S(x, t))

    with ``background = mu_rate * time_multiplier(t) * value_map``,
    ``excitation`` decaying as ``exp(-dt / excitation_omega)`` (new parents
    enter only if the rollout samples them; each adds
    ``excitation_alpha / excitation_omega * N(x; x_i, excitation_sigma^2 I)``),
    and ``S`` the sum of ``suppression_terms``, each with its own decay
    constant and peak-1 Gaussian footprint.
    """

    t: float
    xs: np.ndarray
    ys: np.ndarray
    dx: float
    dy: float
    dA: float
    value_map: np.ndarray
    mu_rate: float
    time_multiplier: float
    background_density: np.ndarray
    excitation_density: np.ndarray
    excitation_alpha: float
    excitation_sigma: float
    excitation_omega: float
    suppression_terms: Tuple[SuppressionTerm, ...]
    suppression_S: np.ndarray
    intensity: np.ndarray
    time_multiplier_fn: Optional[Callable[[float], float]] = None

    def copy(self) -> "SESTPPForecastState":
        """Deep-copy the grids so a rollout can mutate its own state freely."""
        return replace(
            self,
            xs=self.xs.copy(),
            ys=self.ys.copy(),
            value_map=self.value_map.copy(),
            background_density=self.background_density.copy(),
            excitation_density=self.excitation_density.copy(),
            suppression_terms=tuple(self.suppression_terms),
            suppression_S=self.suppression_S.copy(),
            intensity=self.intensity.copy(),
        )


class ConsistentOnlineSESTPP(OnlineSESTPP):
    """Planner intensity model with the SAME functional form as the simulator truth.

    Truth (DeterrentSystem): background density ``mu_true * w(x)``; each
    accepted event spawns Poisson(alpha) offspring with Exp(mean omega) delay
    and N(x_i, sigma^2 I) displacement; candidates are thinned with
    ``exp(-S)``, ``S = sum_k q_k beta_k exp(-|x-x_k|^2/(2 sigma_k^2)) exp(-(t-tau_k)/omega_k)``.

    This model keeps, per robot and with the PLANNER's own parameters
    (``alpha, sigma, omega`` here; per-intervention ``q_hat*beta, sigma, omega``
    supplied by the caller):

        lam_hat(x, t) = [mu_hat * m(t) * w(x) + exc_hat(x, t)] * exp(-S_hat(x, t))
        exc_hat(x, t) = sum_{detected i} alpha / omega * exp(-(t - t_i)/omega) * N(x; x_i, sigma^2 I)

    All grids are densities per m^2 per s; integrate with ``dA = dx * dy``.
    Kernels are evaluated exactly at the grid nodes relative to the exact
    event position (no truncation, no snapping to the nearest node).

    Backward-compatible attributes (read by legacy consumers):
      * ``mu``           = mu_hat * w(x)  (consumers multiply by ``time_multiplier(t)``)
      * ``trigger_mass`` = exc_hat (density)
      * ``lam``          = lam_hat
      * ``inhib_mass``   = (mu*m + exc_hat) * (1 - exp(-S_hat)), the additive
        equivalent of the multiplicative suppression, so the legacy identity
        ``lam = mu*m + trigger_mass - inhib_mass`` still holds exactly.
      * ``suppression_S`` = S_hat.

    Modeling conditions (deliberate, not simplifications):
      * Partial observability / detection thinning. Excitation is stamped only
        for DETECTED events (own detections plus relayed neighbour
        detections). Undetected parents, which in the truth also spawn
        offspring, are missing, so exc_hat is a thinned version of the true
        excitation (expected thinning factor = detection probability times
        range coverage at the parent's time and place). The planner does not
        inflate alpha to compensate; alpha is its belief about the per-event
        branching ratio.
      * Background scalar estimation. ``mu_hat`` is a Gamma-Poisson posterior
        mean under online EM. The owning robot's detected point process has
        intensity ``p_d * 1[x in zone, |x - pose| <= R] * lam_hat``. Each local
        detection contributes its background responsibility
        ``r_i = mu_hat m w(x_i) / (mu_hat m w(x_i) + exc_hat(x_i))`` (the
        exp(-S) factor cancels), and the background exposure is
        ``E = int p_d m(t) sum_{covered nodes} w exp(-S_hat) dA dt``; then
        ``mu_hat = (c0 + sum r_i) / (c0 / mu0 + E)`` with prior pseudo-count c0
        around the prior rate mu0. This is the MLE fixed point as c0 -> 0.
        Responsibilities are evaluated once with the state at detection time
        (standard online EM; they are not revisited), and w and exc_hat are
        read at the nearest node.
      * Time multiplier ``m(t)`` defaults to the constant 1 because the
        simulator truth has no circadian factor. Pass ``time_multiplier_fn``
        when the environment has one (the same function should then drive
        the truth).
    """

    estimator_mode = "consistent"

    def __init__(self, x_min, x_max, y_min, y_max, nx, ny, *,
                 alpha: float, sigma: float, omega: float,
                 mu_init: float, mu_prior_count: float = 5.0,
                 detection_prob: float = 1.0,
                 value_map: Optional[np.ndarray] = None,
                 time_multiplier_fn: Optional[Callable[[float], float]] = None,
                 omega_inhib: float = 600.0, alpha_in: float = 0.25, alpha_cross: float = 0.10,
                 alpha_inhib: float = 0.20, bg_ema: float = 1e-6,
                 term_prune_tol: float = 1e-12):
        super().__init__(x_min, x_max, y_min, y_max, nx, ny,
                         sigma=sigma, omega=omega, omega_inhib=omega_inhib,
                         alpha_in=alpha_in, alpha_cross=alpha_cross, alpha_inhib=alpha_inhib,
                         mu_base=float(mu_init), bg_ema=bg_ema)
        self.alpha = float(alpha)
        self.dA = float(self.dx * self.dy)
        self.detection_prob = float(detection_prob)
        self.time_multiplier_fn = time_multiplier_fn
        self.term_prune_tol = float(term_prune_tol)
        self.value_map = np.ones((ny, nx), float) if value_map is None else np.array(value_map, dtype=float)
        if self.value_map.shape != (ny, nx):
            raise ValueError(f"value_map shape {self.value_map.shape} != {(ny, nx)}")
        self.mu_prior_rate = max(float(mu_init), 1e-300)
        self.mu_prior_count = max(float(mu_prior_count), 1e-12)
        self.bg_responsibility_sum = 0.0
        self.bg_exposure = 0.0
        self.local_detection_count = 0
        self.mu_rate = float(mu_init)
        self.suppression_S = np.zeros((ny, nx), float)
        self._supp_channels: Dict[float, np.ndarray] = {}
        self.suppression_terms: List[SuppressionTerm] = []
        self.intervention_history: List[SuppressionTerm] = []
        self.excitation_events: List[Tuple[float, float, float, float]] = []  # (x, y, t, weight)
        self._refresh_mu_grid()
        self._update_lambda()

    # ---- background ---------------------------------------------------------
    def time_multiplier(self, t: float) -> float:
        fn = self.time_multiplier_fn
        return 1.0 if fn is None else float(fn(float(t)))

    def set_value_map(self, value_map: np.ndarray):
        """Install the planner's value map w(x) on the node grid (shape (ny, nx))."""
        w = np.array(value_map, dtype=float)
        if w.shape != (self.ny, self.nx):
            raise ValueError(f"value_map shape {w.shape} != {(self.ny, self.nx)}")
        self.value_map = w
        self._refresh_mu_grid()
        self._update_lambda()

    def set_background_rate(self, mu_rate: float, *, freeze: bool = False):
        """Reset the background scalar (tests / oracle studies).

        ``freeze=True`` makes the prior overwhelmingly strong so later
        detections and exposure do not move the estimate.
        """
        self.mu_prior_rate = max(float(mu_rate), 1e-300)
        if freeze:
            self.mu_prior_count = 1e300
        self.bg_responsibility_sum = 0.0
        self.bg_exposure = 0.0
        self.mu_rate = float(mu_rate)
        self._refresh_mu_grid()
        self._update_lambda()

    def _refresh_mu_rate(self):
        c0 = self.mu_prior_count
        num = c0 + self.bg_responsibility_sum
        den = c0 / self.mu_prior_rate + self.bg_exposure
        rate = float(num / den) if den > 0 else float(self.mu_prior_rate)
        self.mu_rate = rate if math.isfinite(rate) else float(self.mu_prior_rate)

    def _refresh_mu_grid(self):
        self.mu = self.mu_rate * self.value_map

    def accumulate_detection_exposure(self, coverage_mask: Optional[np.ndarray], dt: float,
                                      detection_prob: Optional[float] = None):
        """Add ``p_d * m(t) * dt * sum_{mask} w exp(-S_hat) dA`` to the background exposure."""
        dt = float(dt)
        if coverage_mask is None or dt <= 0.0:
            return
        mask = np.asarray(coverage_mask, dtype=bool)
        if not mask.any():
            return
        p_d = self.detection_prob if detection_prob is None else float(detection_prob)
        if p_d <= 0.0:
            return
        keep = np.exp(-self.suppression_S[mask])
        self.bg_exposure += p_d * dt * self.time_multiplier(self.t_now) * float(
            np.sum(self.value_map[mask] * keep)) * self.dA
        self._refresh_mu_rate()
        self._refresh_mu_grid()
        self._update_lambda()

    # ---- kernels ------------------------------------------------------------
    def peak_one_gaussian(self, x: float, y: float, sigma: float) -> np.ndarray:
        """exp(-|node - (x, y)|^2 / (2 sigma^2)) on the node grid (no truncation)."""
        s2 = max(float(sigma) ** 2, 1e-9)
        gx = np.exp(-0.5 * (self.xs - float(x)) ** 2 / s2)
        gy = np.exp(-0.5 * (self.ys - float(y)) ** 2 / s2)
        return np.outer(gy, gx)

    def gaussian_density(self, x: float, y: float, sigma: float) -> np.ndarray:
        """Isotropic 2-D normal density N(node; (x, y), sigma^2 I) per m^2."""
        s2 = max(float(sigma) ** 2, 1e-9)
        return self.peak_one_gaussian(x, y, sigma) / (2.0 * math.pi * s2)

    # ---- dynamics -----------------------------------------------------------
    def _update_lambda(self):
        base = self.mu * self.time_multiplier(self.t_now) + self.trigger_mass
        self.lam = base * np.exp(-self.suppression_S)
        self.inhib_mass = base - self.lam

    def _refresh_inhib_mass(self):
        """No-op: ``inhib_mass`` is derived in ``_update_lambda`` for this model."""

    def _refresh_suppression(self):
        total = np.zeros((self.ny, self.nx), float)
        for grid in self._supp_channels.values():
            total += grid
        self.suppression_S = total

    def _prune_terms(self):
        tol = self.term_prune_tol
        t = self.t_now
        self.suppression_terms = [
            term for term in self.suppression_terms
            if term.amplitude * math.exp(-max(t - term.tau, 0.0) / max(term.omega, 1e-9)) > tol
        ]

    def advance_time(self, dt: float):
        if dt <= 0:
            return
        self.trigger_mass *= math.exp(-dt / max(self.omega, 1e-9))
        for omega_key, grid in self._supp_channels.items():
            grid *= math.exp(-dt / max(omega_key, 1e-9))
        self.t_now += dt
        self._refresh_suppression()
        self._prune_terms()
        self._update_lambda()

    def advance_to(self, t: float):
        """Advance model time to ``t`` if it lies in the future (no-op otherwise)."""
        dt = float(t) - float(self.t_now)
        if dt > 0.0:
            self.advance_time(dt)

    def _event_time(self, t: Optional[float]) -> float:
        return float(self.t_now) if t is None else float(t)

    def _lag_decay(self, t_event: float, omega: float) -> float:
        """Decay applied when an event older than ``t_now`` is stamped late."""
        lag = float(self.t_now) - float(t_event)
        return math.exp(-lag / max(float(omega), 1e-9)) if lag > 0.0 else 1.0

    def _stamp_excitation(self, x, y, weight: float, t_event: float):
        amp = self.alpha * float(weight) / max(self.omega, 1e-9) * self._lag_decay(t_event, self.omega)
        self.trigger_mass += amp * self.gaussian_density(x, y, self.sigma)
        self.excitation_events.append((float(x), float(y), float(t_event), float(weight)))

    def add_local_event(self, x, y, t: Optional[float] = None):
        """Own detection: update the background estimate, then stamp excitation."""
        t_event = self._event_time(t)
        iy, ix = self.world_to_idx(x, y)
        bg = float(self.mu[iy, ix]) * self.time_multiplier(t_event)
        ex = float(self.trigger_mass[iy, ix])
        resp = bg / (bg + ex) if (bg + ex) > 0.0 else 1.0
        self.bg_responsibility_sum += resp
        self.local_detection_count += 1
        self._refresh_mu_rate()
        self._refresh_mu_grid()
        self._stamp_excitation(x, y, 1.0, t_event)
        self._update_lambda()

    def add_cross_event(self, x, y, weight=1.0, sigma=None, omega=None, t: Optional[float] = None):
        """Relayed detection: excitation only (its exposure belongs to the owner).

        ``sigma``/``omega`` are accepted for API compatibility and ignored:
        the planner's own excitation kernel is used for every parent.
        """
        self._stamp_excitation(x, y, float(weight), self._event_time(t))
        self._update_lambda()

    def add_intervention_event(self, x, y, weight=1.0, sigma=None, omega_inhib=None, *,
                               mode=None, action_id=None, t: Optional[float] = None):
        """Add one suppression term with amplitude ``weight`` (= q_hat * beta).

        Peak-1 (unnormalised) Gaussian footprint, as in the truth.
        """
        t_event = self._event_time(t)
        sigma_val = self.sigma if sigma is None else float(sigma)
        omega_val = self.omega if omega_inhib is None else float(omega_inhib)
        amp = float(weight)
        term = SuppressionTerm(
            x=float(x), y=float(y), tau=t_event, amplitude=amp, sigma=sigma_val, omega=omega_val,
            mode=self._canonical_intervention_mode(mode),
            action_id=None if action_id is None else int(action_id),
        )
        self.intervention_history.append(term)
        self.suppression_terms.append(term)
        grid = self._supp_channels.get(omega_val)
        if grid is None:
            grid = np.zeros((self.ny, self.nx), float)
            self._supp_channels[omega_val] = grid
        grid += amp * self._lag_decay(t_event, omega_val) * self.peak_one_gaussian(x, y, sigma_val)
        self._refresh_suppression()
        self._update_lambda()

    # ---- accessors ----------------------------------------------------------
    def intensity_at(self, x: float, y: float, t: Optional[float] = None) -> float:
        """Off-grid evaluation of lam_hat from the stored event lists.

        Background uses the nearest-node value map (the truth samples
        background positions per node cell); excitation and suppression are
        summed exactly over the recorded parents and terms.
        """
        t_eval = self.t_now if t is None else float(t)
        iy, ix = self.world_to_idx(x, y)
        bg = self.mu_rate * self.time_multiplier(t_eval) * float(self.value_map[iy, ix])
        s2 = max(self.sigma ** 2, 1e-9)
        ex = 0.0
        for (xi, yi, ti, wi) in self.excitation_events:
            dt = t_eval - ti
            if dt < 0:
                continue
            ex += (self.alpha * wi / self.omega * math.exp(-dt / self.omega)
                   * math.exp(-0.5 * ((x - xi) ** 2 + (y - yi) ** 2) / s2) / (2.0 * math.pi * s2))
        S = 0.0
        for term in self.intervention_history:
            S += float(term.value(x, y, t_eval))
        return float((bg + ex) * math.exp(-S))

    def forecast_state(self) -> SESTPPForecastState:
        """Return a copy-safe snapshot of the component grids for a rollout engine."""
        m = self.time_multiplier(self.t_now)
        return SESTPPForecastState(
            t=float(self.t_now),
            xs=self.xs.copy(),
            ys=self.ys.copy(),
            dx=float(self.dx),
            dy=float(self.dy),
            dA=float(self.dA),
            value_map=self.value_map.copy(),
            mu_rate=float(self.mu_rate),
            time_multiplier=float(m),
            background_density=self.mu * m,
            excitation_density=self.trigger_mass.copy(),
            excitation_alpha=float(self.alpha),
            excitation_sigma=float(self.sigma),
            excitation_omega=float(self.omega),
            suppression_terms=tuple(self.suppression_terms),
            suppression_S=self.suppression_S.copy(),
            intensity=self.lam.copy(),
            time_multiplier_fn=self.time_multiplier_fn,
        )

    def to_tracking_dict(self, *, include_arrays: bool = False, max_items: int = 50):
        out = super().to_tracking_dict(include_arrays=include_arrays, max_items=max_items)
        out.update({
            "estimator_mode": "consistent",
            "alpha": float(self.alpha),
            "mu_rate": float(self.mu_rate),
            "mu_prior_rate": float(self.mu_prior_rate),
            "mu_prior_count": float(self.mu_prior_count),
            "bg_responsibility_sum": float(self.bg_responsibility_sum),
            "bg_exposure": float(self.bg_exposure),
            "local_detection_count": int(self.local_detection_count),
            "suppression_terms_active": int(len(self.suppression_terms)),
            "intervention_history_total": int(len(self.intervention_history)),
            "excitation_events_total": int(len(self.excitation_events)),
        })
        return out


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
