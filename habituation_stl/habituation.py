"""
habituation.py -- per-(cell, cue-mode) deterrence effectiveness state.

Implements the habituation dynamics of the proposal:
  recovery (Eq. 6):   eta(t+dt) = 1 - (1 - eta(t)) * exp(-dt / T_rec)
  habituation (Eq. 7): on a mode-c action in cell z: eta[z,c] *= (1 - kappa_c)
  optional cross-mode generalization: eta[z,c'] *= (1 - gamma * kappa_c)

Effectiveness eta in (0, 1] scales the suppressive power of a deterrence action
in the ground-truth process (Eq. 8) and in the planner's forward predictor
(Eqs. 25-26). Repeating a cue at a place drives eta down (less suppression);
absence lets it recover; rotating modes / spreading in space keeps it high.

This object is the single piece of NEW STATE the ground-truth process and the
planner share. See README_INTEGRATION.md for the one-line edit to the existing
DeterrentSystem truth-suppression term.

Dependencies: numpy only.
"""
from __future__ import annotations

import numpy as np


class HabituationField:
    """Effectiveness state over n_cells x n_modes.

    Parameters
    ----------
    n_cells : int
        Number of spatial cells/zones being tracked.
    n_modes : int
        Number of deterrence cue modes.
    T_rec : float
        Recovery time constant (seconds). Larger -> slower recovery -> stronger
        cumulative habituation.
    kappa : float or sequence
        Per-application habituation increment in (0,1). Scalar broadcasts to all
        modes; sequence gives per-mode values.
    gamma : float
        Cross-mode generalization coupling in [0,1). 0 = independent modes.
    eta0 : float
        Initial effectiveness (default 1.0 = fully effective).
    """

    def __init__(self, n_cells, n_modes, T_rec=1800.0, kappa=0.35, gamma=0.0, eta0=1.0):
        self.n_cells = int(n_cells)
        self.n_modes = int(n_modes)
        self.T_rec = float(T_rec)
        self.gamma = float(gamma)
        if np.isscalar(kappa):
            self.kappa = np.full(self.n_modes, float(kappa))
        else:
            self.kappa = np.asarray(kappa, dtype=float)
            assert self.kappa.shape == (self.n_modes,)
        self.eta = np.full((self.n_cells, self.n_modes), float(eta0))

    # -- dynamics ----------------------------------------------------------
    def recover(self, dt):
        """Exponential recovery of all (cell, mode) effectiveness (Eq. 6)."""
        decay = np.exp(-float(dt) / self.T_rec)
        self.eta = 1.0 - (1.0 - self.eta) * decay

    def apply(self, cell, mode):
        """Apply a completed mode-`mode` action in `cell` (Eq. 7).

        Habituates the applied mode and (if gamma>0) other modes in the cell.
        """
        c = int(cell)
        m = int(mode)
        self.eta[c, m] *= (1.0 - self.kappa[m])
        if self.gamma > 0.0:
            for mm in range(self.n_modes):
                if mm != m:
                    self.eta[c, mm] *= (1.0 - self.gamma * self.kappa[m])

    # -- queries -----------------------------------------------------------
    def effectiveness(self, cell, mode):
        """Current effectiveness eta[cell, mode] in (0,1]."""
        return float(self.eta[int(cell), int(mode)])

    def best_mode(self, cell):
        """Mode with highest current effectiveness in `cell` (variety-seeking)."""
        return int(np.argmax(self.eta[int(cell)]))

    def cell_max_effectiveness(self, cell):
        return float(np.max(self.eta[int(cell)]))

    def copy(self):
        """Deep copy for counterfactual rollouts (used by task_value)."""
        h = HabituationField(self.n_cells, self.n_modes, self.T_rec,
                             self.kappa.copy(), self.gamma)
        h.eta = self.eta.copy()
        return h
