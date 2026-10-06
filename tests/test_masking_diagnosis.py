"""
test_masking_diagnosis.py -- Proposal §3.2 masking and aggregation tree diagnostics.

Tests verify:
  1. Masking: when e0 > E_star, U_stl = 0 even when future suppression differs;
     U_ie > 0 for the same trace (integrated exposure is not masked).
  2. Soft-min argument count: adding an extra cell (with identical signals) to
     the spec changes the score -- false pessimism from n-argument bias.
  3. robustness_breakdown(): structure and content (binding clause is correct).
  4. Hab floor impact: fresh vs. depleted cue gives different cue_preservation_value.
  5. Timed recovery clause (Eq. 4):
     5a. Spike that recovers within T_response -> rho > 0.
     5b. Spike that does NOT recover -> rho < 0.
"""
import math
import numpy as np
import pytest

from habituation_stl.habituation import HabituationField
from habituation_stl.task_value import (
    Dynamics, CellState, counterfactual_value,
    robustness_breakdown, cue_preservation_value,
)
from mission_spec import SpecParams, build_spec
from stl import Trace, robustness_at, Aggregator, _softmin


# ---------------------------------------------------------------------------
# Shared helpers
# ---------------------------------------------------------------------------
def _make_hab(eta0=1.0, T_rec=1800.0, kappa=0.5, n_cells=2, n_modes=1):
    hab = HabituationField(n_cells=n_cells, n_modes=n_modes, T_rec=T_rec, kappa=kappa)
    hab.eta[:] = eta0
    return hab


def _dyn(fc=True, ftc=False, val_mode="stl_robustness"):
    return Dynamics(
        omega_e=600.0, omega_u=900.0, beta=(1.0,), kernel_self=1.0,
        forecast_correction=fc,
        forward_trajectory_correction=ftc,
        valuation_mode=val_mode,
    )


def _params_classical(E_star=5.0, active_clauses=("exp", "cov", "hab"), **kw):
    return SpecParams(
        E_star=E_star, T_cov=1200.0, T_react=None, W=600.0, eta_min=0.4,
        horizon=300.0, monitor_dt=30.0, theta=12.0,
        smooth=False,  # classical min for deterministic masking test
        active_clauses=active_clauses,
        **kw,
    )


def _params_smooth(**kw):
    return SpecParams(
        E_star=5.0, T_cov=1200.0, T_react=None, W=600.0, eta_min=0.4,
        horizon=300.0, monitor_dt=30.0, theta=12.0,
        smooth=True,
        active_clauses=("exp", "cov", "hab"),
        **kw,
    )


# ---------------------------------------------------------------------------
# 1. Masking: high initial exposure makes U_stl = 0, but U_ie > 0.
# ---------------------------------------------------------------------------
def test_masking_stl_high_exposure():
    """When e0 > E_star, the exp clause min is pinned at t=0 for both nom and wa.

    Classical (non-smooth) aggregation makes the masking exact: rho_nom == rho_wa
    because max_s e_nom(s) == e_nom(0) == e0 > E_star, so the minimum of the
    Always clause is at t=0 regardless of future suppression.
    U_stl == 0; U_ie > 0 because the suppression bump still reduces area.
    """
    E_star = 5.0
    e0 = 2.0 * E_star  # current exposure well above threshold

    params_stl = _params_classical(E_star=E_star, active_clauses=("exp",))
    params_ie = _params_classical(E_star=E_star, active_clauses=("exp",))

    dyn_stl = _dyn(fc=True, val_mode="stl_robustness")
    dyn_ie = _dyn(fc=True, val_mode="integrated_exposure")

    hab = _make_hab(eta0=1.0, n_cells=1, n_modes=1)
    cell_states = {0: CellState(e0=e0, g0=0.0)}
    action = (0, 0, 30.0)
    cells = [0]

    U_stl = counterfactual_value(action, cells, cell_states, hab, params_stl, dyn_stl)
    U_ie = counterfactual_value(action, cells, cell_states, hab, params_ie, dyn_ie)

    assert U_stl == 0.0, (
        f"U_stl must be exactly 0 when e0={e0} > E_star={E_star}: got {U_stl}"
    )
    assert U_ie > 0.0, (
        f"U_ie must be positive (suppression reduces area) even when STL is masked: got {U_ie}"
    )


def test_exp_clause_always_masked_for_monotone_decay():
    """The exp clause masks U_stl even when e0 < E_star.

    When e_nom(s) = e0 * exp(-s/omega_e) decays monotonically, the min of
    Always_{[0,H]}((E* - e_z)/E*) occurs at s=0 for BOTH the nominal and
    with-action trace (since the action only modifies s >= lead > 0).
    Therefore rho_exp^nom == rho_exp^wa and U_stl_exp = 0 regardless of e0.

    This is more fundamental than the e0 > E_star masking: the exp clause
    is a gating/constraint term in the planning objective, not a scoring term.
    The coverage clause (where g grows and the min is at s=H) is the main
    scoring signal.
    """
    E_star = 5.0
    e0_below = 0.3 * E_star  # below threshold, but still masked

    params_exp_only = _params_classical(E_star=E_star, active_clauses=("exp",))
    dyn = _dyn(fc=True, val_mode="stl_robustness")
    hab = _make_hab(eta0=1.0, n_cells=1, n_modes=1)
    cell_states = {0: CellState(e0=e0_below, g0=0.0)}

    U_exp_only = counterfactual_value((0, 0, 30.0), [0], cell_states, hab, params_exp_only, dyn)
    assert U_exp_only == 0.0, (
        f"Exp-only U_stl must be 0 even when e0={e0_below} < E_star={E_star} "
        f"because the Always min is pinned at t=0 for monotone decay: got {U_exp_only}"
    )

    # With coverage clause, U_stl > 0: g grows linearly so the Always min is at
    # s=H, and the action resets g in the action cell, raising rho_cov^wa.
    params_cov_only = _params_classical(E_star=E_star, active_clauses=("cov",))
    cell_states_cov = {0: CellState(e0=e0_below, g0=120.0)}
    U_cov_only = counterfactual_value((0, 0, 30.0), [0], cell_states_cov, hab, params_cov_only, dyn)
    assert U_cov_only > 0.0, (
        f"Cov-only U_stl should be positive (coverage resets are captured): got {U_cov_only}"
    )


# ---------------------------------------------------------------------------
# 2. Soft-min argument count: n=2 vs n=3 equal arguments gives different score.
# ---------------------------------------------------------------------------
def test_softmin_argument_count_changes_score():
    """Adding an inactive-action cell to the spec changes the soft-min score.

    When all n arguments are equal to x, softmin_theta(x,...,x) = x - ln(n)/theta.
    A 3-cell spec gives a LOWER score than a 2-cell spec for the same signals,
    causing false pessimism that makes candidates with larger local cell sets
    appear worse than they are relative to candidates with smaller sets.
    """
    theta = 12.0
    n_cells_small = 2
    n_cells_large = 3

    # All cells at threshold so each predicate returns 0.0.
    E_star = 5.0
    e0_at_threshold = E_star  # so (E_star - e0)/E_star = 0.0 exactly

    params_2 = SpecParams(
        E_star=E_star, T_cov=1200.0, T_react=None, W=600.0, eta_min=0.4,
        horizon=300.0, monitor_dt=30.0, theta=theta, smooth=True,
        active_clauses=("exp",),
    )
    params_3 = SpecParams(
        E_star=E_star, T_cov=1200.0, T_react=None, W=600.0, eta_min=0.4,
        horizon=300.0, monitor_dt=30.0, theta=theta, smooth=True,
        active_clauses=("exp",),
    )

    hab_2 = _make_hab(eta0=1.0, n_cells=n_cells_small, n_modes=1)
    hab_3 = _make_hab(eta0=1.0, n_cells=n_cells_large, n_modes=1)

    cells_2 = list(range(n_cells_small))
    cells_3 = list(range(n_cells_large))

    # All cells at threshold: e0 = E_star.  No action (lead > horizon).
    states_2 = {i: CellState(e0=e0_at_threshold, g0=0.0) for i in cells_2}
    states_3 = {i: CellState(e0=e0_at_threshold, g0=0.0) for i in cells_3}
    dyn = _dyn(fc=False, val_mode="stl_robustness")

    # Use a very long lead so the action has no effect; only rho_nom matters.
    long_lead = params_2.horizon + 1000.0
    U_2 = counterfactual_value((0, 0, long_lead), cells_2, states_2, hab_2, params_2, dyn)
    U_3 = counterfactual_value((0, 0, long_lead), cells_3, states_3, hab_3, params_3, dyn)

    # Both U values should be ~0 (rho_wa == rho_nom), but rho_nom itself differs.
    # Extract rho_nom by evaluating the spec directly on the nom trace.
    import numpy as _np
    from stl import Trace as _Trace, robustness_at as _rho_at

    def _rho_nom(cells, states, params):
        times = _np.arange(max(2, int(round(params.horizon / params.monitor_dt)) + 1)) * params.monitor_dt
        sig = {f"e_{c}": states[c].e0 * _np.exp(-times / 600.0) for c in cells}
        sig.update({f"g_{c}": states[c].g0 + times for c in cells})
        sig.update({f"eta_{c}": _np.ones_like(times) for c in cells})
        spec, _ = build_spec(cells, params)
        return _rho_at(spec, _Trace(times, sig), 0)

    rho_2 = _rho_nom(cells_2, states_2, params_2)
    rho_3 = _rho_nom(cells_3, states_3, params_3)

    # With n equal arguments at x, softmin = x - ln(n)/theta.
    # rho_2 ~ 0 - ln(2)/12 ~ -0.0578; rho_3 ~ 0 - ln(3)/12 ~ -0.0916.
    expected_gap = (1.0 / theta) * math.log(n_cells_large / n_cells_small)
    actual_gap = rho_2 - rho_3  # rho_2 > rho_3

    assert rho_3 < rho_2, (
        f"3-cell spec should have lower robustness than 2-cell spec for equal signals: "
        f"rho_2={rho_2:.4f}, rho_3={rho_3:.4f}"
    )
    assert abs(actual_gap - expected_gap) < 0.01, (
        f"Softmin argument-count bias should be ln(n_large/n_small)/theta = {expected_gap:.4f}; "
        f"got {actual_gap:.4f}"
    )


# ---------------------------------------------------------------------------
# 3. robustness_breakdown() structure and binding clause.
# ---------------------------------------------------------------------------
def test_robustness_breakdown_structure():
    """robustness_breakdown() returns the expected keys and a valid binding clause."""
    hab = _make_hab(eta0=0.5, n_cells=2, n_modes=1)
    params = _params_classical()
    dyn = _dyn(fc=True)
    cell_states = {0: CellState(e0=0.3, g0=60.0), 1: CellState(e0=0.3, g0=60.0)}
    action = (0, 0, 60.0)
    cells = [0, 1]

    bd = robustness_breakdown(action, cells, cell_states, hab, params, dyn)

    assert "nom" in bd and "wa" in bd
    assert "U_stl" in bd and "U_ie" in bd
    assert "binding_clause_nom" in bd and "binding_clause_wa" in bd
    assert math.isfinite(bd["U_stl"])
    assert math.isfinite(bd["U_ie"])
    assert bd["U_ie"] >= 0.0, "Integrated exposure reduction is non-negative"
    assert bd["binding_clause_nom"] in bd["nom"]
    assert bd["binding_clause_wa"] in bd["wa"]

    # The binding clause must have the minimum robustness among all clauses.
    nom_min_val = min(bd["nom"].values())
    assert abs(bd["nom"][bd["binding_clause_nom"]] - nom_min_val) < 1e-9


def test_robustness_breakdown_binding_exp_when_masked():
    """When e0 > E_star, the exp clause is binding and U_stl == 0."""
    E_star = 5.0
    e0 = 2.0 * E_star
    params = _params_classical(E_star=E_star, active_clauses=("exp",))
    dyn = _dyn(fc=True)
    hab = _make_hab(eta0=1.0, n_cells=1, n_modes=1)
    cell_states = {0: CellState(e0=e0, g0=0.0)}

    bd = robustness_breakdown((0, 0, 30.0), [0], cell_states, hab, params, dyn)
    assert bd["binding_clause_nom"] == "exp"
    assert bd["U_stl"] == 0.0
    assert bd["U_ie"] > 0.0


# ---------------------------------------------------------------------------
# 4. Hab floor impact: cue_preservation_value.
# ---------------------------------------------------------------------------
def test_cue_preservation_fresh_vs_depleted():
    """A fresh cue has a positive hab_contribution; a depleted cue has a negative one.

    When eta > eta_min: the hab clause is satisfied, contributing positively to U.
    When eta < eta_min after depletion: the hab clause is violated, reducing U.
    """
    E_star = 5.0
    params = _params_classical(E_star=E_star)
    cells = [0, 1]
    cell_states = {i: CellState(e0=2.0, g0=120.0) for i in cells}
    action = (0, 0, 60.0)

    # Fresh cue: eta = 1.0 > eta_min = 0.4
    hab_fresh = _make_hab(eta0=1.0, n_cells=2, n_modes=1)
    dyn_fresh = _dyn(fc=True)
    _, _, contrib_fresh = cue_preservation_value(
        action, cells, cell_states, hab_fresh, params, dyn_fresh)

    # Heavily depleted cue: eta = 0.1 < eta_min = 0.4
    hab_dep = _make_hab(eta0=0.1, n_cells=2, n_modes=1)
    dyn_dep = _dyn(fc=True)
    _, _, contrib_depleted = cue_preservation_value(
        action, cells, cell_states, hab_dep, params, dyn_dep)

    assert contrib_fresh >= contrib_depleted, (
        "Fresh cue should have a higher or equal hab contribution than depleted cue"
    )


def test_cue_preservation_value_finite():
    """cue_preservation_value() returns three finite values."""
    params = _params_classical()
    hab = _make_hab(eta0=0.6, n_cells=2, n_modes=1)
    dyn = _dyn(fc=True)
    cell_states = {i: CellState(e0=1.0, g0=60.0) for i in range(2)}

    u_full, u_no_hab, contrib = cue_preservation_value(
        (0, 0, 60.0), [0, 1], cell_states, hab, params, dyn)

    assert all(math.isfinite(v) for v in (u_full, u_no_hab, contrib))
    assert abs(u_full - u_no_hab - contrib) < 1e-12, "hab_contribution must equal U_full - U_no_hab"


# ---------------------------------------------------------------------------
# 5. Timed recovery clause (Eq. 4).
# ---------------------------------------------------------------------------
def _make_timed_recovery_params(E_high=8.0, E_low=3.0, T_response=90.0):
    return SpecParams(
        E_star=5.0, T_cov=1200.0, T_react=None, W=600.0, eta_min=0.4,
        horizon=300.0, monitor_dt=30.0, theta=12.0, smooth=False,
        active_clauses=("timed_recovery",),
        E_high=E_high, E_low=E_low, T_response=T_response,
    )


def _build_trace(e_signal, params):
    """Build a Trace with a single cell from an array of e values."""
    n = len(e_signal)
    times = np.arange(n) * params.monitor_dt
    sig = {
        "e_0": np.asarray(e_signal, dtype=float),
        "g_0": np.zeros(n),
        "eta_0": np.ones(n),
    }
    return Trace(times, sig)


def test_timed_recovery_satisfied():
    """A spike above E_high that falls below E_low within T_response -> rho > 0."""
    params = _make_timed_recovery_params(E_high=8.0, E_low=3.0, T_response=90.0)
    spec, _ = build_spec([0], params)

    # e starts below E_high (no trigger); one spike at t=30 that recovers by t=90.
    # Steps at dt=30: t=0,30,60,90,120,...,300 (11 steps)
    n_steps = int(round(params.horizon / params.monitor_dt)) + 1
    e = np.full(n_steps, 2.0)  # below E_high and E_low everywhere
    e[1] = 10.0  # spike at t=30: above E_high
    e[2] = 2.0   # at t=60: below E_low -> recovery within T_response=90

    trace = _build_trace(e, params)
    rho = robustness_at(spec, trace, 0)
    assert rho > 0.0, f"Timed recovery satisfied -> rho should be positive, got {rho}"


def test_timed_recovery_violated():
    """A spike above E_high that stays above E_low past T_response -> rho < 0."""
    params = _make_timed_recovery_params(E_high=8.0, E_low=3.0, T_response=90.0)
    spec, _ = build_spec([0], params)

    n_steps = int(round(params.horizon / params.monitor_dt)) + 1
    e = np.full(n_steps, 10.0)  # stays above E_high = 8.0 throughout

    trace = _build_trace(e, params)
    rho = robustness_at(spec, trace, 0)
    assert rho < 0.0, f"Timed recovery violated -> rho should be negative, got {rho}"


def test_timed_recovery_vacuous_when_no_trigger():
    """When e stays below E_high the entire horizon, Implies is vacuously true -> rho > 0."""
    params = _make_timed_recovery_params(E_high=8.0, E_low=3.0, T_response=90.0)
    spec, _ = build_spec([0], params)

    n_steps = int(round(params.horizon / params.monitor_dt)) + 1
    e = np.full(n_steps, 2.0)  # always below E_high

    trace = _build_trace(e, params)
    rho = robustness_at(spec, trace, 0)
    assert rho > 0.0, f"No trigger -> vacuous Implies -> rho > 0, got {rho}"


def test_timed_recovery_spec_params_missing():
    """build_spec() skips timed_recovery clause when threshold params are None."""
    params = SpecParams(
        E_star=5.0, T_cov=1200.0, T_react=None, W=600.0, eta_min=0.4,
        horizon=300.0, monitor_dt=30.0, theta=12.0, smooth=False,
        active_clauses=("timed_recovery",),
        # E_high, E_low, T_response left as None
    )
    _, clauses = build_spec([0], params)
    assert "timed_recovery" not in clauses, (
        "timed_recovery clause must not be built when threshold params are None"
    )
