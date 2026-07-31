"""
metrics.py -- run-level metrics for the baseline ladder (Sec. 8.4).

Primary:        value-weighted exposure J_exp, reactive deadline miss rate,
                coverage-violation time.
Specification:  run robustness (global + per-clause), via RobotMonitor.
Habituation:    mean effectiveness at deterrence moments (eta_bar), cue-variety
                index, habituation-attributable exposure.
Efficiency:     travel distance, number of actions.
"""
from __future__ import annotations

import math
from collections import defaultdict

import numpy as np


class RunMetrics:
    def __init__(self, n_cells, eta_min=0.4):
        self.n_cells = n_cells
        self.eta_min = eta_min
        self.J_exp = 0.0                      # value-weighted exposure (Eq. 9)
        self.coverage_violation_time = 0.0    # cell-seconds over T_cov
        self.reactive_total = 0
        self.reactive_missed = 0
        self.travel = 0.0
        self.actions = 0
        self._eta_at_apply = []               # effectiveness at each action
        self._mode_use = defaultdict(lambda: defaultdict(int))  # cell -> mode -> count
        self._hab_attrib_exposure = 0.0       # exposure attributable to low-eta actions

    # -- accumulation ------------------------------------------------------
    def add_exposure(self, value_weighted_increment):
        self.J_exp += float(value_weighted_increment)

    def add_coverage_violation(self, cell_seconds_over):
        self.coverage_violation_time += float(cell_seconds_over)

    def reactive_arrival(self):
        self.reactive_total += 1

    def reactive_miss(self):
        self.reactive_missed += 1

    def add_travel(self, dist):
        self.travel += float(dist)

    def record_action(self, cell, mode, eta_at_apply):
        self.actions += 1
        self._eta_at_apply.append(float(eta_at_apply))
        self._mode_use[cell][mode] += 1

    def add_habituation_attributable_exposure(self, amt):
        self._hab_attrib_exposure += float(amt)

    # -- summaries ---------------------------------------------------------
    def eta_bar(self):
        return float(np.mean(self._eta_at_apply)) if self._eta_at_apply else float("nan")

    def deadline_miss_rate(self):
        return (self.reactive_missed / self.reactive_total) if self.reactive_total else 0.0

    def variety_index(self):
        """Mean normalized Shannon entropy of cue-mode usage across active cells.

        1.0 = perfectly varied cue usage; 0.0 = always the same cue. Captures the
        anti-habituation behavior phi_hab is meant to induce.
        """
        ents = []
        for cell, modes in self._mode_use.items():
            counts = np.array(list(modes.values()), dtype=float)
            if counts.sum() <= 0:
                continue
            p = counts / counts.sum()
            k = len(p)
            if k <= 1:
                ents.append(0.0)
                continue
            ent = -np.sum(p * np.log(p + 1e-12)) / math.log(k)
            ents.append(float(ent))
        return float(np.mean(ents)) if ents else float("nan")

    def hab_attributable_exposure(self):
        return float(self._hab_attrib_exposure)

    def as_dict(self):
        return {
            "J_exp": self.J_exp,
            "deadline_miss_rate": self.deadline_miss_rate(),
            "coverage_violation_time": self.coverage_violation_time,
            "eta_bar": self.eta_bar(),
            "variety_index": self.variety_index(),
            "hab_attributable_exposure": self.hab_attributable_exposure(),
            "actions": self.actions,
            "travel": self.travel,
        }
