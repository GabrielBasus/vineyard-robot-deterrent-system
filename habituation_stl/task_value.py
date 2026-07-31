"""
task_value.py -- predictive task value as counterfactual STL robustness margin.

Implements Algorithm 2 and the cheap analytic forward predictor (Eqs. 25-26):

  U(a, r) = rho_tilde(Phi_r, xi^{+a}, [t, t+H]) - rho_tilde(Phi_r, xi^{-a}, [t, t+H])

This is the single quantity that REPLACES the prior dJ score
(`estimate_counterfactual_reduction`) everywhere in the pipeline.

The forward predictor rolls the local per-cell signals over the horizon:
  - exposure e_z decays passively (background regeneration cancels in the
    difference); the candidate action subtracts an effectiveness-scaled
    suppression bump in its cell from the completion lead onward (Eq. 26),
  - coverage age g_z grows linearly and resets to 0 in the action cell at
    completion,
  - the anti-habituation signal eta_z in the action cell is set to the
    application-time effectiveness of the chosen mode (penalizing a habituated
    cue), and is 1.0 (vacuously satisfied) where no action is active.

Because U is a difference of robustness margins, choosing a habituated mode is
penalized through phi_hab even when it would still reduce instantaneous
exposure -- exactly the behavior a scalar exposure objective cannot produce.
"""
from __future__ import annotations

from dataclasses import dataclass

import numpy as np

from stl import Trace, robustness_at
from mission_spec import SpecParams, build_spec


@dataclass
class Dynamics:
    """Forward-prediction dynamics parameters."""
    omega_e: float = 600.0     # passive exposure-decay time constant (s)
    omega_u: float = 900.0     # suppression-decay time constant (s)
    beta: tuple = (1.0,)       # per-mode nominal suppression strength
    kernel_self: float = 1.0   # self-cell suppression kernel peak (normalized)


@dataclass
class CellState:
    """Current observed state of one local cell."""
    e0: float        # current value-weighted exposure rate
    g0: float        # current coverage age (s since last serviced)


def _times(params: SpecParams):
    n = max(2, int(round(params.horizon / params.monitor_dt)) + 1)
    return np.arange(n) * params.monitor_dt


def _nominal_signals(cells, cell_states, times, dyn: Dynamics):
    sig = {}
    for c in cells:
        st = cell_states[c]
        sig[f"e_{c}"] = st.e0 * np.exp(-times / dyn.omega_e)
        sig[f"g_{c}"] = st.g0 + times
        sig[f"eta_{c}"] = np.ones_like(times)  # no active deterrence -> vacuous
    return sig


def counterfactual_value(action, cells, cell_states, hab, params: SpecParams,
                         dyn: Dynamics, reactive_ids=None):
    """U(a, r) for a candidate predictive action.

    action      : (cell, mode, completion_lead_s)
    cells       : iterable of local cell ids comprising Phi_r
    cell_states : dict cell -> CellState
    hab         : HabituationField (read-only; not mutated)
    """
    a_cell, a_mode, lead = int(action[0]), int(action[1]), float(action[2])
    times = _times(params)
    spec, _ = build_spec(cells, params, reactive_ids)

    # Nominal trajectory xi^{-a}
    nom = _nominal_signals(cells, cell_states, times, dyn)
    nom_trace = Trace(times, nom)
    rho_nom = robustness_at(spec, nom_trace, 0)

    # With-action trajectory xi^{+a}: copy nominal, modify the action cell.
    wa = {k: v.copy() for k, v in nom.items()}
    if "hab" in set(str(clause) for clause in params.active_clauses):
        eta_app = hab.effectiveness(a_cell, a_mode)        # effectiveness AT application
    else:
        eta_app = 1.0                                    # no-hab STL baselines assume a fresh cue
    beta_c = float(dyn.beta[a_mode]) if a_mode < len(dyn.beta) else float(dyn.beta[-1])

    e_nom_cell = nom[f"e_{a_cell}"]
    supp = np.zeros_like(times)
    after = times >= lead
    # effectiveness-scaled, decaying suppression injected from completion (Eq. 26),
    # capped by the available exposure in the cell.
    supp[after] = (eta_app * beta_c * dyn.kernel_self
                   * np.exp(-(times[after] - lead) / dyn.omega_u))
    wa[f"e_{a_cell}"] = np.maximum(0.0, e_nom_cell - np.minimum(e_nom_cell, supp))

    # coverage reset at completion
    g = wa[f"g_{a_cell}"].copy()
    g[after] = times[after] - lead
    wa[f"g_{a_cell}"] = g

    # anti-habituation: chosen mode's application effectiveness from completion on
    eta_sig = wa[f"eta_{a_cell}"].copy()
    eta_sig[after] = eta_app
    wa[f"eta_{a_cell}"] = eta_sig

    wa_trace = Trace(times, wa)
    rho_wa = robustness_at(spec, wa_trace, 0)

    return float(rho_wa - rho_nom)


def best_action_for_cell(a_cell, cells, cell_states, hab, params: SpecParams,
                         dyn: Dynamics, completion_lead=60.0, reactive_ids=None):
    """Pick the cue mode maximizing U for a candidate cell; return (mode, U).

    The habituation clause makes this prefer un-habituated modes automatically.
    """
    best_m, best_u = 0, -np.inf
    for m in range(hab.n_modes):
        u = counterfactual_value((a_cell, m, completion_lead), cells, cell_states,
                                 hab, params, dyn, reactive_ids)
        if u > best_u:
            best_m, best_u = m, u
    return best_m, float(best_u)
