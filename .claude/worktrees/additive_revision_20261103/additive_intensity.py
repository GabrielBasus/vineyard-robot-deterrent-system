"""Explicit finite-volume primitives for the additive alignment work.

The explicit additive simulator mode and estimator share these primitives.
Fields are rate densities (events / square metre / second); Gaussian kernels
are cell probabilities, not densities. Callers supply all physical amplitudes.
"""
from dataclasses import dataclass

import numpy as np
from scipy.special import ndtr

ADDITIVE_CONTRACT = "additive_cells_v1"


def cell_mass_kernel(sigma, dx, dy, radius):
    """Cell-integrated Gaussian centred on a cell, without renormalization."""
    if not all(np.isfinite(v) and v > 0 for v in (sigma, dx, dy)):
        raise ValueError("kernel dimensions must be finite and positive")
    edges = np.arange(-radius, radius + 2, dtype=float) - .5
    px = np.diff(ndtr(edges * dx / sigma))
    py = np.diff(ndtr(edges * dy / sigma))
    return np.outer(py, px)


def _nonnegative(value, name):
    a = np.asarray(value, dtype=float)
    if not np.all(np.isfinite(a)) or np.any(a < 0):
        raise ValueError(f"{name} must be finite and nonnegative")
    return a


def positive_part_intensity(background, excitation, inhibition):
    """Return lambda_plus, lambda, and acceptance under the same measure.

    Zero dominating intensity has zero acceptance, including when u is zero.
    Inputs are never mutated. Scalars and broadcastable fields are supported.
    """
    bg = _nonnegative(background, "background")
    exc = _nonnegative(excitation, "excitation")
    inh = _nonnegative(inhibition, "inhibition")
    candidate, inh = np.broadcast_arrays(bg + exc, inh)
    intensity = np.maximum(candidate - inh, 0.0)
    probability = np.divide(intensity, candidate, out=np.zeros_like(intensity),
                            where=candidate > 0)
    return candidate, intensity, probability


@dataclass(frozen=True)
class CellGrid:
    """Equal-area cells with absorbing Gaussian boundaries.

    This is an explicit proposed discretization, not the legacy node/jitter
    geometry. Out-of-domain Gaussian probability is discarded, never rescaled.
    """
    width: float
    height: float
    nx: int
    ny: int

    def __post_init__(self):
        if not np.isfinite(self.width) or not np.isfinite(self.height):
            raise ValueError("domain dimensions must be finite")
        if self.width <= 0 or self.height <= 0:
            raise ValueError("domain dimensions must be positive")
        for count in (self.nx, self.ny):
            if isinstance(count, bool) or not isinstance(count, (int, np.integer)) or count < 1:
                raise ValueError("cell counts must be positive integers")

    @property
    def area(self):
        return self.width * self.height / (self.nx * self.ny)

    def index(self, x, y):
        if not np.isfinite(x) or not np.isfinite(y) or not (0 <= x <= self.width and 0 <= y <= self.height):
            raise ValueError("location must lie inside the field")
        return (min(int(y * self.ny / self.height), self.ny - 1),
                min(int(x * self.nx / self.width), self.nx - 1))

    def centre(self, x, y):
        iy, ix = self.index(x, y)
        return ((ix + .5) * self.width / self.nx,
                (iy + .5) * self.height / self.ny)

    def gaussian_mass(self, x, y, sigma):
        """Integral of a unit-integral R2 Gaussian over each cell, y then x."""
        if not all(np.isfinite(v) for v in (x, y, sigma)) or sigma <= 0:
            raise ValueError("Gaussian location must be finite and sigma positive")
        px = np.diff(ndtr((np.linspace(0, self.width, self.nx + 1) - x) / sigma))
        py = np.diff(ndtr((np.linspace(0, self.height, self.ny + 1) - y) / sigma))
        return np.outer(py, px)

    def rate_density(self, x, y, sigma, initial_rate):
        """Convert an explicitly supplied events/second amplitude to density."""
        rate = _nonnegative(initial_rate, "initial_rate")
        if rate.ndim:
            raise ValueError("initial_rate must be scalar")
        return float(rate) * self.gaussian_mass(x, y, sigma) / self.area

    def background_density(self, physical_mu, spatial_weights):
        """Preserve legacy total demand mu * mean(weights) * W * H.

        Weights are supplied explicitly, e.g. legacy value-map samples. This
        preserves aggregate demand and cell-index probabilities, not the old
        clipped within-cell location distribution.
        """
        mu = _nonnegative(physical_mu, "physical_mu")
        weights = _nonnegative(spatial_weights, "spatial_weights")
        if mu.ndim or weights.shape != (self.ny, self.nx):
            raise ValueError("expected scalar mu and a (ny,nx) spatial map")
        return float(mu) * weights


def offspring_initial_rate(branching_mean, decay_seconds, step_seconds=None):
    """Convert offspring count to rate; never reinterpret count as rate.

    Continuous exponential density has initial rate alpha/omega. For an
    explicitly discrete next-step process, use geometric-bin mass/dt; its
    integrated infinite sum is alpha. This function chooses no default dt.
    """
    alpha = _nonnegative(branching_mean, "branching_mean")
    if alpha.ndim or not np.isfinite(decay_seconds) or decay_seconds <= 0:
        raise ValueError("expected scalar count and positive finite decay")
    if step_seconds is None:
        return float(alpha) / decay_seconds
    if not np.isfinite(step_seconds) or step_seconds <= 0:
        raise ValueError("step must be positive and finite")
    return float(alpha) * (-np.expm1(-step_seconds / decay_seconds)) / step_seconds


class AdditiveGridTruth:
    """Predictable, stepwise additive process with coupled background proposals.

    Excitation is an aggregate conditional Poisson rate, not a pre-drawn tree.
    New accepted events contribute from the next step only. Beta is an initial
    total rate, and every source is snapped to its cell centre before applying
    a Gaussian. The physical background rate is never divided by cell area.
    """
    def __init__(self, grid, weights, *, branching_mean, sigma, omega, dt):
        self.grid = grid
        self.weights = np.array(_nonnegative(weights, "weights"), copy=True)
        if self.weights.shape != (grid.ny, grid.nx):
            raise ValueError("weight shape must match the grid")
        self.gain = offspring_initial_rate(branching_mean, omega, dt)
        if not np.isfinite(sigma) or sigma <= 0:
            raise ValueError("excitation sigma must be finite and positive")
        self.sigma, self.omega, self.dt = float(sigma), float(omega), float(dt)
        self.decay = np.exp(-dt / omega)
        self.excitation = np.zeros_like(self.weights)
        self.candidate = np.zeros_like(self.weights)
        self.inhibition = np.zeros_like(self.weights)
        self.intensity = np.zeros_like(self.weights)
        self.probability = np.zeros_like(self.weights)
        self.parts = []
        self._open = False
        self._last_t = None
        self._kernel_cache = {}

    def kernel(self, x, y, sigma):
        cx, cy = self.grid.centre(x, y)
        key = cx, cy, float(sigma)
        if key not in self._kernel_cache:
            # Bound retained kernels: memory does not grow with intervention history.
            if len(self._kernel_cache) >= 256:
                self._kernel_cache.clear()
            field = self.grid.gaussian_mass(cx, cy, sigma) / self.grid.area
            field.flags.writeable = False
            self._kernel_cache[key] = field
        return self._kernel_cache[key]

    def begin_step(self, t, mu, interventions):
        if self._open:
            raise RuntimeError("finish the previous additive step first")
        if not np.isfinite(t):
            raise ValueError("time must be finite")
        if self._last_t is not None and not np.isclose(t-self._last_t, self.dt, rtol=0, atol=1e-7):
            raise ValueError("additive truth requires consecutive fixed time steps")
        bg = self.grid.background_density(mu, self.weights)
        inhibition = np.zeros_like(bg)
        self.parts = []
        for event in interventions:
            age = float(t) - float(event["t"])
            if age < 0:
                continue
            beta = float(_nonnegative(event["beta"], "beta"))
            eta = float(_nonnegative(event.get("eta", 1.), "eta"))
            omega = float(event["omega"])
            if not np.isfinite(omega) or omega <= 0 or eta > 1:
                raise ValueError("invalid intervention decay or effectiveness")
            amp = beta * eta * np.exp(-age / omega)
            k = self.kernel(float(event["x"]), float(event["y"]), float(event["sigma"]))
            inhibition += amp * k
            self.parts.append((amp, k, str(event.get("mode", "unknown")),
                               str(event.get("source", "direct_detection"))))
        self.candidate, self.intensity, self.probability = positive_part_intensity(bg, self.excitation, inhibition)
        self.inhibition = inhibition
        self.background = bg
        self._open = True
        self._last_t = float(t)

    def proposals(self, streams, step_index):
        if not self._open:
            raise RuntimeError("begin additive step before sampling")
        out = []
        # Distinct IDs: (step,0,k) background and (step,1,k) excitation.
        for origin, rates, rng in (
                (0, self.background, streams.background_rng),
                (1, self.excitation, streams.offspring_rng((int(step_index), 1)))):
            flat = np.maximum(rates.ravel(), 0.)
            total = float(flat.sum())
            count = int(rng.poisson(total * self.grid.area * self.dt))
            if count == 0:
                continue
            cdf = np.cumsum(flat) / total
            # The background draws depend only on seed, time and physical demand.
            for k in range(count):
                index = min(int(np.searchsorted(cdf, rng.random(), side="right")), flat.size-1)
                iy, ix = divmod(index, self.grid.nx)
                x = (ix + float(rng.random())) * self.grid.width / self.grid.nx
                y = (iy + float(rng.random())) * self.grid.height / self.grid.ny
                out.append((x, y, self._last_t, (int(step_index), origin, k),
                            "background" if origin == 0 else "offspring"))
        return out

    def suppression_at(self, x, y):
        if not self._open:
            raise RuntimeError("begin additive step before querying suppression")
        iy, ix = self.grid.index(x, y)
        keep = float(self.probability[iy, ix])
        suppress = 1. - keep if self.candidate[iy, ix] > 0 else 0.
        total = float(self.inhibition[iy, ix])
        modes, sources = {}, {}
        if total > 0:
            for amp, kernel, mode, source in self.parts:
                part = suppress * amp * float(kernel[iy, ix]) / total
                modes[mode] = modes.get(mode, 0.) + part
                sources[source] = sources.get(source, 0.) + part
        return keep, suppress, modes, sources

    def finish_step(self, accepted_locations):
        if not self._open:
            raise RuntimeError("no additive step is open")
        excitation = self.excitation * self.decay
        for x, y in accepted_locations:
            excitation += self.gain * self.kernel(x, y, self.sigma)
        self.excitation = excitation
        self._open = False
