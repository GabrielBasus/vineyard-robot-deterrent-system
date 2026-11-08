"""Tests for mission_spec.py and task_value.py."""
import numpy as np

from mission_spec import SpecParams, build_spec
from stl import Trace, robustness_at
from habituation import HabituationField
from task_value import Dynamics, CellState, counterfactual_value, best_action_for_cell


def test_spec_satisfied_vs_violated():
    cells = [0, 1]
    params = SpecParams(E_star=5.0, T_cov=1200.0, eta_min=0.4, horizon=120.0,
                        monitor_dt=30.0, smooth=False)
    spec, clauses = build_spec(cells, params)
    n = int(params.horizon / params.monitor_dt) + 1
    t = np.arange(n) * params.monitor_dt

    # All clauses comfortably satisfied
    good = {}
    for c in cells:
        good[f"e_{c}"] = np.full(n, 1.0)      # below E*=5
        good[f"g_{c}"] = np.full(n, 100.0)    # below T_cov
        good[f"eta_{c}"] = np.full(n, 0.9)    # above eta_min
    assert robustness_at(spec, Trace(t, good), 0) > 0

    # Exposure clause violated in one cell
    bad = {k: v.copy() for k, v in good.items()}
    bad["e_0"] = np.full(n, 9.0)              # above E*=5 -> violation
    assert robustness_at(spec, Trace(t, bad), 0) < 0
    assert robustness_at(clauses["exp"], Trace(t, bad), 0) < 0
    assert robustness_at(clauses["cov"], Trace(t, bad), 0) > 0


def test_clause_weights_scale_global_robustness():
    cells = [0]
    base = SpecParams(E_star=5.0, T_cov=1200.0, eta_min=0.4, horizon=0.0,
                      monitor_dt=30.0, smooth=False, active_clauses=("exp",),
                      clause_weights={"exp": 1.0})
    weighted = SpecParams(E_star=5.0, T_cov=1200.0, eta_min=0.4, horizon=0.0,
                          monitor_dt=30.0, smooth=False, active_clauses=("exp",),
                          clause_weights={"exp": 3.0})
    t = np.array([0.0])
    trace = Trace(t, {"e_0": np.array([6.0]), "g_0": np.array([0.0]), "eta_0": np.array([1.0])})

    base_spec, _ = build_spec(cells, base)
    weighted_spec, _ = build_spec(cells, weighted)

    assert np.isclose(robustness_at(weighted_spec, trace, 0), 3.0 * robustness_at(base_spec, trace, 0))

def test_counterfactual_value_positive_when_exposure_high():
    cells = [0]
    params = SpecParams(E_star=2.0, T_cov=1200.0, eta_min=0.4, horizon=300.0,
                        monitor_dt=30.0, smooth=True, theta=12.0)
    dyn = Dynamics(omega_e=600.0, omega_u=900.0, beta=(3.0, 3.0))
    hab = HabituationField(n_cells=1, n_modes=2, T_rec=1800.0, kappa=0.45)
    # cell is over-exposed -> a fresh-mode deterrence should raise robustness
    states = {0: CellState(e0=6.0, g0=900.0)}
    u_fresh = counterfactual_value((0, 0, 60.0), cells, states, hab, params, dyn)
    assert u_fresh > 0


def test_no_hab_spec_scores_cue_as_fresh():
    cells = [0]
    with_hab = SpecParams(E_star=2.0, T_cov=1200.0, eta_min=0.4, horizon=300.0,
                          monitor_dt=30.0, smooth=True, theta=12.0,
                          active_clauses=("exp", "cov", "hab"))
    no_hab = SpecParams(E_star=2.0, T_cov=1200.0, eta_min=0.4, horizon=300.0,
                        monitor_dt=30.0, smooth=True, theta=12.0,
                        active_clauses=("exp", "cov"))
    dyn = Dynamics(beta=(3.0, 3.0))
    hab = HabituationField(n_cells=1, n_modes=2, T_rec=1800.0, kappa=0.5)
    states = {0: CellState(e0=6.0, g0=900.0)}

    for _ in range(4):
        hab.apply(0, 0)

    u_hab_mode0 = counterfactual_value((0, 0, 60.0), cells, states, hab, with_hab, dyn)
    u_nohab_mode0 = counterfactual_value((0, 0, 60.0), cells, states, hab, no_hab, dyn)
    u_nohab_mode1 = counterfactual_value((0, 1, 60.0), cells, states, hab, no_hab, dyn)

    assert u_nohab_mode0 > u_hab_mode0, (u_nohab_mode0, u_hab_mode0)
    assert np.isclose(u_nohab_mode0, u_nohab_mode1), (u_nohab_mode0, u_nohab_mode1)

def test_value_penalizes_habituated_cue():
    cells = [0]
    params = SpecParams(E_star=2.0, T_cov=1200.0, eta_min=0.4, horizon=300.0,
                        monitor_dt=30.0, smooth=True, theta=12.0)
    dyn = Dynamics(beta=(3.0, 3.0))
    hab = HabituationField(n_cells=1, n_modes=2, T_rec=1800.0, kappa=0.5)
    states = {0: CellState(e0=6.0, g0=900.0)}

    # Heavily habituate mode 0; mode 1 stays fresh.
    for _ in range(4):
        hab.apply(0, 0)
    u_habituated = counterfactual_value((0, 0, 60.0), cells, states, hab, params, dyn)
    u_fresh = counterfactual_value((0, 1, 60.0), cells, states, hab, params, dyn)
    assert u_fresh > u_habituated, (u_fresh, u_habituated)

    # best_action_for_cell should therefore prefer the fresh mode (mode 1)
    m, u = best_action_for_cell(0, cells, states, hab, params, dyn)
    assert m == 1
    print(f"    U(fresh mode 1)={u_fresh:.4f}  U(habituated mode 0)={u_habituated:.4f}"
          f"  -> chosen mode={m}")


def run_all():
    fns = [v for k, v in globals().items() if k.startswith("test_") and callable(v)]
    for fn in fns:
        fn()
        print(f"  PASS {fn.__name__}")
    print(f"mission_spec.py + task_value.py: {len(fns)}/{len(fns)} tests passed")


if __name__ == "__main__":
    run_all()
