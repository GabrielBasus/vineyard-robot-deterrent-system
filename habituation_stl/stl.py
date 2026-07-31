"""
stl.py -- Signal Temporal Logic robustness monitor.

Implements the quantitative (robustness) semantics from the proposal
(Eqs. 12-19), with both classical min/max conjunction/disjunction and the
*smooth* softmin/softmax surrogate (Eq. 20) that avoids the flat-gradient
pathology that defeated the prior hand-tuned dJ value function.

Operators implemented:
  Boolean : Pred, Neg, And, Or, Implies
  Future  : Eventually_[a,b], Always_[a,b], Until_[a,b]
  Past    : Once_[a,b], Historically_[a,b], Since_[a,b]

Signals are interpreted over a UNIFORMLY-sampled trace (sampling period dt =
monitor period Delta_m). Robustness of a formula is returned as an array
aligned to the trace time grid; robustness_at() reads a single query time.

Bounded temporal operators use truncated-horizon semantics at the trace
boundaries (windows are clamped to the available samples). Keep buffers at
least as long as the largest temporal bound so truncation does not bite.

Dependencies: numpy only.
"""
from __future__ import annotations

import math
import numpy as np


# ---------------------------------------------------------------------------
# Smooth / classical aggregation
# ---------------------------------------------------------------------------
def _softmin(arr, theta, axis=None):
    arr = np.asarray(arr, dtype=float)
    if axis is None:
        m = float(np.min(arr))
        s = float(np.sum(np.exp(-theta * (arr - m))))
        return m - (1.0 / theta) * np.log(s)
    m = np.min(arr, axis=axis, keepdims=True)
    s = np.sum(np.exp(-theta * (arr - m)), axis=axis, keepdims=True)
    res = m - (1.0 / theta) * np.log(s)
    return np.squeeze(res, axis=axis)


def _softmax(arr, theta, axis=None):
    arr = np.asarray(arr, dtype=float)
    if axis is None:
        M = float(np.max(arr))
        s = float(np.sum(np.exp(theta * (arr - M))))
        return M + (1.0 / theta) * np.log(s)
    M = np.max(arr, axis=axis, keepdims=True)
    s = np.sum(np.exp(theta * (arr - M)), axis=axis, keepdims=True)
    res = M + (1.0 / theta) * np.log(s)
    return np.squeeze(res, axis=axis)


class Aggregator:
    """Conjunction (amin) and disjunction (amax) aggregator.

    mode='classical' -> exact min/max (sound robustness).
    mode='smooth'    -> softmin/softmax with temperature theta; differentiable,
                        gradient-bearing, and -> min/max as theta -> infinity.
    """

    def __init__(self, mode: str = "classical", theta: float = 12.0):
        assert mode in ("classical", "smooth")
        self.mode = mode
        self.theta = float(theta)

    def amin(self, arr, axis=None):
        if self.mode == "classical":
            return np.min(arr, axis=axis)
        return _softmin(arr, self.theta, axis)

    def amax(self, arr, axis=None):
        if self.mode == "classical":
            return np.max(arr, axis=axis)
        return _softmax(arr, self.theta, axis)


# ---------------------------------------------------------------------------
# Trace
# ---------------------------------------------------------------------------
class Trace:
    """A uniformly-sampled multi-signal trace.

    times   : 1D array of sample times (uniform spacing assumed)
    signals : dict name -> 1D array (same length as times)
    """

    def __init__(self, times, signals):
        self.t = np.asarray(times, dtype=float)
        self.n = int(len(self.t))
        if self.n >= 2:
            self.dt = float(self.t[1] - self.t[0])
        else:
            self.dt = 1.0
        self.signals = {k: np.asarray(v, dtype=float) for k, v in signals.items()}
        for k, v in self.signals.items():
            if len(v) != self.n:
                raise ValueError(f"signal '{k}' length {len(v)} != trace length {self.n}")


def _window(i, n, lo_off, hi_off):
    """Clamped index window [lo, hi] for offsets relative to i.

    Truncated-horizon semantics: clamp to [0, n-1]; if the clamped window is
    empty, fall back to the single nearest in-range sample.
    """
    lo = i + lo_off
    hi = i + hi_off
    lo_c = max(0, lo)
    hi_c = min(n - 1, hi)
    if lo_c > hi_c:
        k = min(max(lo, 0), n - 1)
        return k, k
    return lo_c, hi_c


# ---------------------------------------------------------------------------
# Formula AST
# ---------------------------------------------------------------------------
class Formula:
    """Base class. eval(trace) -> robustness array aligned to trace.t."""

    def eval(self, trace: Trace) -> np.ndarray:  # pragma: no cover - abstract
        raise NotImplementedError


class Pred(Formula):
    """Atomic predicate. func(trace) returns a robustness array (Eq. 12)."""

    def __init__(self, func, name: str = "pred"):
        self.func = func
        self.name = name

    def eval(self, trace):
        return np.asarray(self.func(trace), dtype=float)


def signal_leq(name, thr, scale=1.0, label=None):
    """Predicate (signal <= thr), robustness = (thr - signal)/scale."""
    scale = float(scale) if scale else 1.0
    return Pred(lambda tr: (thr - tr.signals[name]) / scale, label or f"{name}<= {thr}")


def signal_geq(name, thr, scale=1.0, label=None):
    """Predicate (signal >= thr), robustness = (signal - thr)/scale."""
    scale = float(scale) if scale else 1.0
    return Pred(lambda tr: (tr.signals[name] - thr) / scale, label or f"{name}>= {thr}")


class Neg(Formula):
    def __init__(self, sub):
        self.sub = sub

    def eval(self, trace):
        return -self.sub.eval(trace)


class Scale(Formula):
    """Scale a subformula's robustness by a constant factor."""

    def __init__(self, sub, weight: float):
        self.sub = sub
        self.weight = float(weight)

    def eval(self, trace):
        return self.weight * self.sub.eval(trace)


class And(Formula):
    def __init__(self, subs, agg: Aggregator | None = None):
        self.subs = list(subs)
        self.agg = agg or Aggregator()

    def eval(self, trace):
        if not self.subs:
            return np.full(trace.n, np.inf)
        stk = np.stack([s.eval(trace) for s in self.subs], axis=0)
        return self.agg.amin(stk, axis=0)


class Or(Formula):
    def __init__(self, subs, agg: Aggregator | None = None):
        self.subs = list(subs)
        self.agg = agg or Aggregator()

    def eval(self, trace):
        if not self.subs:
            return np.full(trace.n, -np.inf)
        stk = np.stack([s.eval(trace) for s in self.subs], axis=0)
        return self.agg.amax(stk, axis=0)


def Implies(ante, cons, agg: Aggregator | None = None):
    """phi -> psi  ==  (not phi) or psi."""
    return Or([Neg(ante), cons], agg=agg)


class _BoundedTemporal(Formula):
    def __init__(self, sub, a, b, agg: Aggregator | None = None):
        self.sub = sub
        self.a = float(a)
        self.b = float(b)
        self.agg = agg or Aggregator()

    def _offsets(self, dt):
        ia = int(math.ceil(self.a / dt - 1e-9))
        ib = int(math.floor(self.b / dt + 1e-9))
        if ib < ia:
            ib = ia
        return ia, ib


class Eventually(_BoundedTemporal):
    """Diamond_[a,b]: robustness = sup over forward window (Eq. 16)."""

    def eval(self, trace):
        r = self.sub.eval(trace)
        n = trace.n
        ia, ib = self._offsets(trace.dt)
        out = np.empty(n)
        for i in range(n):
            lo, hi = _window(i, n, ia, ib)
            out[i] = self.agg.amax(r[lo:hi + 1])
        return out


class Always(_BoundedTemporal):
    """Box_[a,b]: robustness = inf over forward window (Eq. 15)."""

    def eval(self, trace):
        r = self.sub.eval(trace)
        n = trace.n
        ia, ib = self._offsets(trace.dt)
        out = np.empty(n)
        for i in range(n):
            lo, hi = _window(i, n, ia, ib)
            out[i] = self.agg.amin(r[lo:hi + 1])
        return out


class Once(_BoundedTemporal):
    """Past 'once' O_[a,b]: sup over backward window (Eq. 18)."""

    def eval(self, trace):
        r = self.sub.eval(trace)
        n = trace.n
        ia, ib = self._offsets(trace.dt)
        out = np.empty(n)
        for i in range(n):
            lo, hi = _window(i, n, -ib, -ia)
            out[i] = self.agg.amax(r[lo:hi + 1])
        return out


class Historically(_BoundedTemporal):
    """Past 'historically' H_[a,b]: inf over backward window (Eq. 19)."""

    def eval(self, trace):
        r = self.sub.eval(trace)
        n = trace.n
        ia, ib = self._offsets(trace.dt)
        out = np.empty(n)
        for i in range(n):
            lo, hi = _window(i, n, -ib, -ia)
            out[i] = self.agg.amin(r[lo:hi + 1])
        return out


class Until(Formula):
    """Bounded until phi1 U_[a,b] phi2 (Eq. 17), discrete uniform grid."""

    def __init__(self, left, right, a, b, agg: Aggregator | None = None):
        self.left = left
        self.right = right
        self.a = float(a)
        self.b = float(b)
        self.agg = agg or Aggregator()

    def eval(self, trace):
        rl = self.left.eval(trace)
        rr = self.right.eval(trace)
        n = trace.n
        dt = trace.dt
        ia = int(math.ceil(self.a / dt - 1e-9))
        ib = int(math.floor(self.b / dt + 1e-9))
        if ib < ia:
            ib = ia
        out = np.empty(n)
        for i in range(n):
            lo = max(i + ia, 0)
            hi = min(i + ib, n - 1)
            if lo > hi:
                k = min(max(i + ia, 0), n - 1)
                lo = hi = k
            cand = []
            for j in range(lo, hi + 1):
                left_inf = self.agg.amin(rl[i:j + 1]) if j >= i else rl[max(i, 0)]
                cand.append(self.agg.amin(np.array([rr[j], left_inf])))
            out[i] = self.agg.amax(np.array(cand))
        return out


class Since(Formula):
    """Bounded since phi1 S_[a,b] phi2 (past dual of Until)."""

    def __init__(self, left, right, a, b, agg: Aggregator | None = None):
        self.left = left
        self.right = right
        self.a = float(a)
        self.b = float(b)
        self.agg = agg or Aggregator()

    def eval(self, trace):
        rl = self.left.eval(trace)
        rr = self.right.eval(trace)
        n = trace.n
        dt = trace.dt
        ia = int(math.ceil(self.a / dt - 1e-9))
        ib = int(math.floor(self.b / dt + 1e-9))
        if ib < ia:
            ib = ia
        out = np.empty(n)
        for i in range(n):
            lo = max(i - ib, 0)
            hi = min(i - ia, n - 1)
            if lo > hi:
                k = min(max(i - ia, 0), n - 1)
                lo = hi = k
            cand = []
            for j in range(lo, hi + 1):
                left_inf = self.agg.amin(rl[j:i + 1]) if i >= j else rl[min(i, n - 1)]
                cand.append(self.agg.amin(np.array([rr[j], left_inf])))
            out[i] = self.agg.amax(np.array(cand))
        return out


# ---------------------------------------------------------------------------
# Top-level helpers
# ---------------------------------------------------------------------------
def robustness(formula: Formula, trace: Trace) -> np.ndarray:
    """Robustness signal over the whole trace."""
    return formula.eval(trace)


def robustness_at(formula: Formula, trace: Trace, t_index: int = 0) -> float:
    """Robustness at a single query index (default: start of window)."""
    return float(formula.eval(trace)[t_index])
