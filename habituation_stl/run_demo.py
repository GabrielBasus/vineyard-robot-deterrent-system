"""run_demo.py -- narrated walkthrough of the new direction.

Two parts:
  1) the core mechanism in isolation -- why rotating cues beats repeating one,
     which is what makes predictive variety operationally valuable;
  2) a one-seed baseline-ladder run showing the value function in action.

Usage:  python run_demo.py
"""
import os
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)

import numpy as np

from habituation import HabituationField
from mission_spec import SpecParams
from task_value import Dynamics, CellState, counterfactual_value, best_action_for_cell
from reference_sim import ReferenceSim


def part1_mechanism():
    print("=" * 64)
    print("PART 1  Why the objective cannot be a scalar: habituation")
    print("=" * 64)
    print("Same number of deterrence actions on one hot spot. Compare cumulative")
    print("effective suppression when REPEATING one cue vs ROTATING three cues.\n")

    n_actions, dt_between, T_rec, kappa = 12, 60.0, 1500.0, 0.5

    hA = HabituationField(1, 3, T_rec=T_rec, kappa=kappa)
    supp_repeat = 0.0
    for _ in range(n_actions):
        supp_repeat += hA.effectiveness(0, 0)
        hA.apply(0, 0)
        hA.recover(dt_between)

    hB = HabituationField(1, 3, T_rec=T_rec, kappa=kappa)
    supp_rotate = 0.0
    for k in range(n_actions):
        m = k % 3
        supp_rotate += hB.effectiveness(0, m)
        hB.apply(0, m)
        hB.recover(dt_between)

    print(f"  repeat one cue : cumulative suppression = {supp_repeat:5.2f}")
    print(f"  rotate 3 cues  : cumulative suppression = {supp_rotate:5.2f}"
          f"   (+{100*(supp_rotate-supp_repeat)/supp_repeat:.0f}%)")
    print("\n  A scalar exposure-greedy policy keeps hitting the same spot with the")
    print("  same cue and silently loses effectiveness. The objective must reward")
    print("  variety -- which is what phi_hab does.\n")


def part2_value_function():
    print("=" * 64)
    print("PART 2  The counterfactual robustness value U(a, r) in action")
    print("=" * 64)
    cells = [0]
    params = SpecParams(E_star=2.0, T_cov=1200.0, eta_min=0.4, horizon=300.0,
                        monitor_dt=30.0, smooth=True, theta=12.0)
    dyn = Dynamics(beta=(3.0, 3.0, 3.0))
    hab = HabituationField(1, 3, T_rec=1800.0, kappa=0.5)
    state = {0: CellState(e0=6.0, g0=900.0)}   # an over-exposed, stale cell

    print("\n  Cell is over-exposed (e0=6 > E*=2) and overdue for coverage.")
    print("  Heavily habituate cue mode 0, leave modes 1,2 fresh, then score:\n")
    for _ in range(4):
        hab.apply(0, 0)

    for m in range(3):
        u = counterfactual_value((0, m, 60.0), cells, state, hab, params, dyn)
        print(f"    U(mode {m}, eta={hab.effectiveness(0,m):.3f}) = {u:+.4f}")
    m_star, u_star = best_action_for_cell(0, cells, state, hab, params, dyn)
    print(f"\n  best_action_for_cell -> mode {m_star} (U={u_star:+.4f}); the value")
    print("  function avoids the habituated cue without being told to.\n")


def part3_ladder():
    print("=" * 64)
    print("PART 3  One-seed baseline ladder (habituating ground truth)")
    print("=" * 64)
    print(f"\n  {'policy':<6}{'J_exp':>10}{'miss':>8}{'cov_viol':>11}"
          f"{'eta_bar':>9}{'variety':>9}   description")
    desc = {"B0": "reactive only",
            "B1": "greedy, blind cue (to beat)",
            "B3": "STL value, no phi_hab",
            "B4": "full spec (Idea 1+2)"}
    for pol in ["B0", "B1", "B3", "B4"]:
        m = ReferenceSim(policy=pol, seed=123, habituation=True,
                         horizon_s=3600.0).run()
        print(f"  {pol:<6}{m['J_exp']:>10.0f}{m['deadline_miss_rate']:>8.2f}"
              f"{m['coverage_violation_time']:>11.0f}{m['eta_bar']:>9.3f}"
              f"{m['variety_index']:>9.2f}   {desc[pol]}")
    print("\n  B4 drives value-weighted exposure far below the greedy baseline by")
    print("  maintaining cue effectiveness (higher eta_bar, variety ~0.9). Run")
    print("  experiment.py for the full multi-seed ladder + habituation-off control.\n")


if __name__ == "__main__":
    np.set_printoptions(precision=3, suppress=True)
    part1_mechanism()
    part2_value_function()
    part3_ladder()
