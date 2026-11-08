"""
test_rollout_cue_dynamics.py -- Plan Section 3 ("value future cue use").

Dynamics.rollout_cue_dynamics carries habituation depletion and recovery through
the greedy continuation rollout (habituation_stl/rollout.py).  Tests verify:
  (a) flag off reproduces the pre-change greedy_rollout values exactly;
  (b) the live HabituationField is never mutated by the rollout;
  (c) with a depleted mode 0 and a fresh mode 1, greedy steps choose mode 1 and
      J_H is lower than under the frozen mode-0 rollout;
  (d) a candidate that spends the only fresh cue the continuation would later
      need gets a lower U(a) with cue dynamics than without (value of
      preserving a cue).
"""
from dataclasses import replace

import numpy as np
import pytest

from habituation_stl.habituation import HabituationField
from habituation_stl.rollout import continuation_value, greedy_rollout
from habituation_stl.task_value import CellState, Dynamics
from mission_spec import SpecParams


def _params():
    return SpecParams(horizon=300.0, monitor_dt=30.0,
                      active_clauses=("exp", "cov", "hab"))


def _dyn(beta=(1.0, 0.8), cue=False):
    return Dynamics(beta=beta, forecast_correction=True,
                    valuation_mode="continuation_rollout",
                    rollout_cue_dynamics=cue)


def _three_cell_case():
    hab = HabituationField(3, 2, T_rec=1800.0, kappa=0.5)
    hab.eta[:] = [[0.9, 0.6], [0.5, 1.0], [0.3, 0.7]]
    cells = [0, 1, 2]
    cs = {0: CellState(4.0, 100.0), 1: CellState(2.5, 50.0), 2: CellState(1.0, 10.0)}
    pending = [(20.0, 1, 0)]
    return hab, cells, cs, pending


class _RecordingHab(HabituationField):
    """HabituationField whose copies log every apply(cell, mode) call."""

    def __init__(self, *args, log=None, **kwargs):
        super().__init__(*args, **kwargs)
        self.log = log if log is not None else []

    def apply(self, cell, mode):
        self.log.append((int(cell), int(mode)))
        super().apply(cell, mode)

    def copy(self):
        h = _RecordingHab(self.n_cells, self.n_modes, self.T_rec,
                          self.kappa.copy(), self.gamma, log=self.log)
        h.eta = self.eta.copy()
        return h


# (a) Reference values computed with greedy_rollout at commit b3b8283 (before
# rollout_cue_dynamics existed) on the three-cell case with n_robots=2.
_REFERENCE_J = {
    None: 1227.7740673051214,
    (0, 1, 60.0): 1274.28867609884,
    (2, 0, 30.0): 1273.3003995157972,
}


@pytest.mark.parametrize("candidate", list(_REFERENCE_J))
def test_flag_off_matches_previous_values_exactly(candidate):
    hab, cells, cs, pending = _three_cell_case()
    j = greedy_rollout(cells, cs, hab, _params(), _dyn(cue=False),
                       candidate=candidate, pending_events=pending, n_robots=2)
    assert j == _REFERENCE_J[candidate]


def test_default_flag_is_off():
    assert Dynamics().rollout_cue_dynamics is False


# (b)
@pytest.mark.parametrize("candidate", [None, (0, 1, 60.0)])
def test_live_hab_not_mutated(candidate):
    hab, cells, cs, pending = _three_cell_case()
    eta_before = hab.eta.copy()
    greedy_rollout(cells, cs, hab, _params(), _dyn(cue=True),
                   candidate=candidate, pending_events=pending, n_robots=2)
    continuation_value((0, 1, 60.0), cells, cs, hab, _params(), _dyn(cue=True),
                       pending_events=pending, n_robots=2)
    np.testing.assert_array_equal(hab.eta, eta_before)


# (c)
def test_greedy_picks_fresh_mode_and_lowers_cost():
    hab = _RecordingHab(1, 2, T_rec=1800.0, kappa=0.5)
    hab.eta[0] = [0.1, 1.0]
    cs = {0: CellState(5.0, 0.0)}

    j_frozen = greedy_rollout([0], cs, hab, _params(), _dyn(beta=(1.0, 1.0), cue=False),
                              n_robots=1)
    assert hab.log == []  # frozen rollout never depletes

    j_cue = greedy_rollout([0], cs, hab, _params(), _dyn(beta=(1.0, 1.0), cue=True),
                           n_robots=1)
    assert hab.log, "cue-dynamics rollout should deplete its copy"
    # First greedy intervention uses the fresh mode 1, not the depleted mode 0.
    assert hab.log[0] == (0, 1)
    np.testing.assert_array_equal(hab.eta[0], [0.1, 1.0])
    assert j_cue < j_frozen


# (d)
def test_spending_the_only_fresh_cue_lowers_value():
    # One cell, mode 0 nearly exhausted, mode 1 fresh; heavy depletion and no
    # meaningful recovery within the horizon.  The candidate uses mode 1, which
    # the greedy continuation would otherwise use for all later interventions.
    hab = HabituationField(1, 2, T_rec=1e6, kappa=0.9)
    hab.eta[0] = [0.05, 1.0]
    cs = {0: CellState(5.0, 0.0)}
    action = (0, 1, 30.0)

    u_frozen = continuation_value(action, [0], cs, hab, _params(),
                                  _dyn(beta=(1.0, 1.0), cue=False), n_robots=1)
    u_cue = continuation_value(action, [0], cs, hab, _params(),
                               _dyn(beta=(1.0, 1.0), cue=True), n_robots=1)
    assert u_cue < u_frozen
    # The frozen rollout credits the candidate with a large benefit because its
    # baseline continuation is stuck on the exhausted mode 0.
    assert u_frozen > 10.0 * max(u_cue, 1e-9)


def test_cue_dynamics_changes_three_cell_values():
    hab, cells, cs, pending = _three_cell_case()
    j_off = greedy_rollout(cells, cs, hab, _params(), _dyn(cue=False),
                           pending_events=pending, n_robots=2)
    j_on = greedy_rollout(cells, cs, hab, _params(), replace(_dyn(), rollout_cue_dynamics=True),
                          pending_events=pending, n_robots=2)
    assert np.isfinite(j_on) and j_on > 0.0
    assert j_on != j_off
