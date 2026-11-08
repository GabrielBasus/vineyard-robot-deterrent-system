"""
signals.py -- decentralized online robustness monitor (Algorithm 1).

Each robot maintains rolling, uniformly-sampled buffers of the local signals
(exposure e_z, coverage age g_z, effectiveness eta_z) over the cells it owns
(plus boundary cells shared by neighbors). At each monitor tick it reports the
run-so-far robustness of each mission clause -- the worst-case (min) normalized
margin over the trailing buffer, i.e. "held historically".

This monitor is used for telemetry/diagnostics and for the reservation
controller; the counterfactual *task value* uses the forward-looking spec in
task_value.py.
"""
from __future__ import annotations

from collections import deque

import numpy as np

from stl import Trace
from mission_spec import SpecParams, build_inner_clauses


class RobotMonitor:
    def __init__(self, cells, params: SpecParams, buffer_len=64):
        self.cells = list(cells)
        self.params = params
        self.inner = build_inner_clauses(self.cells, params)
        self.buf_t = deque(maxlen=buffer_len)
        self.buf = {f"e_{c}": deque(maxlen=buffer_len) for c in self.cells}
        self.buf.update({f"g_{c}": deque(maxlen=buffer_len) for c in self.cells})
        self.buf.update({f"eta_{c}": deque(maxlen=buffer_len) for c in self.cells})

    def record(self, t, exposures, coverage_ages, active_modes, hab):
        """Append one sample (Algorithm 1, lines 1-5).

        exposures      : dict cell -> e_z
        coverage_ages  : dict cell -> g_z
        active_modes   : dict cell -> mode (or None if no deterrence active)
        hab            : HabituationField (for the eta_z signal)
        """
        self.buf_t.append(float(t))
        for c in self.cells:
            self.buf[f"e_{c}"].append(float(exposures.get(c, 0.0)))
            self.buf[f"g_{c}"].append(float(coverage_ages.get(c, 0.0)))
            m = active_modes.get(c, None)
            eta = 1.0 if m is None else hab.effectiveness(c, m)
            self.buf[f"eta_{c}"].append(float(eta))

    def _trace(self):
        n = len(self.buf_t)
        t = np.asarray(self.buf_t, dtype=float)
        signals = {k: np.asarray(v, dtype=float) for k, v in self.buf.items()}
        return Trace(t, signals), n

    def robustness(self):
        """Return dict {clause -> run-so-far robustness, 'global' -> smooth min}."""
        if len(self.buf_t) < 1:
            return {"global": float("inf")}
        trace, n = self._trace()
        agg = self.params.aggregator()
        out = {}
        for name, formula in self.inner.items():
            r = formula.eval(trace)          # robustness over the buffer
            out[name] = float(np.min(r))     # held historically -> worst sample
        if out:
            out["global"] = float(agg.amin(np.array(list(out.values()))))
        else:
            out["global"] = float("inf")
        return out
