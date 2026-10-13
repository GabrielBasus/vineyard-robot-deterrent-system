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

valuation_mode options (set on Dynamics):
  "stl_robustness"       -- default; return rho(xi^{+a}) - rho(xi^{-a})
  "integrated_exposure"  -- return integral of exposure reduction over [lead, H]
                            (Plan §3 variant C objective)
"""
from __future__ import annotations

from dataclasses import dataclass, replace

import numpy as np

from stl import Trace, robustness_at
from mission_spec import SpecParams, build_spec


@dataclass
class Dynamics:
    """Forward-prediction dynamics parameters."""
    omega_e: float = 600.0          # passive exposure-decay time constant (s)
    omega_u: float = 900.0          # suppression-decay time constant (s)
    beta: tuple = (1.0,)            # per-mode nominal suppression strength
    kernel_self: float = 1.0        # self-cell suppression kernel peak (normalized)
    # Proposal §2: when True, activates consistent-forecast corrections (Eqs. 1, 2,
    # chronological intervening events, post-application recovery trace).
    # When False (default), preserves variant A behavior exactly.
    forecast_correction: bool = False
    # Proposal §2 (forward trajectory): when True, propagates background, trigger, and
    # inhibitory components of e_nom separately over the horizon instead of collapsing
    # them into a single e0*exp(-s/omega_e) curve.  Requires CellState.trigger0,
    # inhib0, and mu0_t to be populated by the caller.  Independent of forecast_correction.
    forward_trajectory_correction: bool = False
    # Proposal §3.1: valuation objective.
    #   "stl_robustness"      -- return rho(xi^{+a}) - rho(xi^{-a})  [default]
    #   "integrated_exposure" -- return sum_s min(e_nom(s), supp(s)) * dt for s >= lead
    #   "continuation_rollout"-- Plan §4: J_H(pi_0) - J_H(pi_a) via greedy rollout
    valuation_mode: str = "stl_robustness"
    # Plan §4: greedy rollout parameters (used when valuation_mode=="continuation_rollout").
    n_robots: int = 4
    avg_travel_s: float = 30.0
    service_hold_s: float = 20.0
    greedy_dt_s: float = 45.0
    # Plan §4 admission gate: return 0 if U(a) <= benefit_gate (prevents negative-U actions).
    benefit_gate: float = 0.0
    # Plan §4E: if True, reject candidate when it delays a feasible reactive task.
    service_protection: bool = False
    # Plan §4 admission: when True, the task generator drops predictive candidates
    # whose U(a) <= benefit_gate instead of dispatching them with a zero score.
    strict_admission: bool = False
    # Diagnostic only: ((field, value), ...) overrides used to re-score each
    # candidate on the same snapshot (e.g. (('forecast_correction', False),)).
    shadow_overrides: tuple = ()


@dataclass
class CellState:
    """Current observed state of one local cell."""
    e0: float        # current value-weighted exposure rate
    g0: float        # current coverage age (s since last serviced)
    # Optional fields for forward_trajectory_correction (Proposal §2).
    # Default 0.0 preserves existing behavior when not supplied.
    trigger0: float = 0.0   # cell-integrated trigger/excitation mass at decision time
    inhib0: float = 0.0     # cell-integrated inhibitory mass at decision time
    mu0_t: float = 0.0      # cell-integrated background rate * time_multiplier at t


def _times(params: SpecParams):
    n = max(2, int(round(params.horizon / params.monitor_dt)) + 1)
    return np.arange(n) * params.monitor_dt


def _nominal_signals(cells, cell_states, times, dyn: Dynamics):
    sig = {}
    for c in cells:
        st = cell_states[c]
        if dyn.forward_trajectory_correction and (st.inhib0 > 0.0 or st.mu0_t > 0.0):
            # Corrected forward trajectory: propagate background (constant), trigger
            # (decays at omega_e), and inhibitory mass (decays at omega_u) separately.
            # e(t+s) = mu0_t + trigger0*exp(-s/omega_e) - inhib0*exp(-s/omega_u).
            # Clipped at 0: rates cannot be negative.
            e_nom = np.maximum(0.0,
                st.mu0_t
                + st.trigger0 * np.exp(-times / dyn.omega_e)
                - st.inhib0 * np.exp(-times / dyn.omega_u)
            )
        else:
            e_nom = st.e0 * np.exp(-times / dyn.omega_e)
        sig[f"e_{c}"] = e_nom
        sig[f"g_{c}"] = st.g0 + times
        sig[f"eta_{c}"] = np.ones_like(times)  # no active deterrence -> vacuous
    return sig


def _compute_q_hat(a_cell, a_mode, lead, hab, dyn, params, pending_events):
    """Compute q_hat (application effectiveness) and eta_post (post-depletion eta).

    Returns (q_hat, eta_post).  q_hat is used both in the suppression amplitude
    and, for STL mode, in the eta trace after application.
    """
    if "hab" in set(str(c) for c in params.active_clauses):
        if dyn.forecast_correction:
            # Proposal §2: copy hab so the live state is never mutated (item 2.6).
            hab_fc = hab.copy()
            t_cursor = 0.0
            # Proposal §2: process known intervening committed applications
            # chronologically, alternating recovery with depletion jumps (item 2.3).
            for t_ev, c_ev, m_ev in sorted(pending_events or [], key=lambda e: e[0]):
                if t_ev >= lead:
                    break
                hab_fc.recover(t_ev - t_cursor)
                hab_fc.apply(c_ev, m_ev)
                t_cursor = t_ev
            # Eq. (1): q̂_a = 1 − [1 − η̂(t)] exp(−δ_a / T̂_rec)
            hab_fc.recover(lead - t_cursor)
            q_hat = hab_fc.effectiveness(a_cell, a_mode)
            # Eq. (2): η̂(t_a+) = (1 − κ̂) q̂_a
            kappa_m = float(hab.kappa[a_mode]) if a_mode < len(hab.kappa) else float(hab.kappa[-1])
            eta_post = (1.0 - kappa_m) * q_hat
        else:
            # Variant A: reads η at decision time, no travel-time recovery.
            q_hat = hab.effectiveness(a_cell, a_mode)
            eta_post = q_hat
    else:
        q_hat = 1.0
        eta_post = 1.0
    return q_hat, eta_post


def _build_wa_signals(nom, a_cell, a_mode, lead, times, after, q_hat, eta_post,
                      e_nom_cell, supp, hab, dyn):
    """Build the with-action signal dict from the nominal signals."""
    wa = {k: v.copy() for k, v in nom.items()}
    wa[f"e_{a_cell}"] = np.maximum(0.0, e_nom_cell - np.minimum(e_nom_cell, supp))

    # Coverage reset at completion.
    g = wa[f"g_{a_cell}"].copy()
    g[after] = times[after] - lead
    wa[f"g_{a_cell}"] = g

    # Eta signal: post-application depletion + exponential recovery.
    eta_sig = wa[f"eta_{a_cell}"].copy()
    if dyn.forecast_correction:
        # Proposal §2: η recovers exponentially from η_post toward 1 after the action.
        eta_sig[after] = 1.0 - (1.0 - eta_post) * np.exp(-(times[after] - lead) / hab.T_rec)
    else:
        # Variant A: flat trace at q̂_a from completion onward.
        eta_sig[after] = q_hat
    wa[f"eta_{a_cell}"] = eta_sig
    return wa


def counterfactual_value(action, cells, cell_states, hab, params: SpecParams,
                         dyn: Dynamics, reactive_ids=None, pending_events=None,
                         fleet_pending_events=None, reactive_tasks=None):
    """U(a, r) for a candidate predictive action.

    action         : (cell, mode, completion_lead_s)
    cells          : iterable of local cell ids comprising Phi_r
    cell_states    : dict cell -> CellState
    hab            : HabituationField (read-only; not mutated)
    reactive_tasks : list of {"deadline_s": float} for Plan §4E service protection

    valuation_mode dispatch:
      "stl_robustness"      -- rho(xi^{+a}) - rho(xi^{-a})
      "integrated_exposure" -- sum_{s>=lead} min(e_nom(s), supp(s)) * dt
      "continuation_rollout"-- J_H(pi_0) - J_H(pi_a) via greedy rollout (Plan §4)
    """
    a_cell, a_mode, lead = int(action[0]), int(action[1]), float(action[2])
    times = _times(params)
    nom = _nominal_signals(cells, cell_states, times, dyn)
    e_nom_cell = nom[f"e_{a_cell}"]
    after = times >= lead

    q_hat, eta_post = _compute_q_hat(a_cell, a_mode, lead, hab, dyn, params, pending_events)

    beta_c = float(dyn.beta[a_mode]) if a_mode < len(dyn.beta) else float(dyn.beta[-1])
    # Remaining approximation: e_nom_cell decays monotonically from the snapshot e0.
    # Historical suppression from past applications is folded into e0 via eta-weighted
    # feedback (Proposal §2 historical-suppression fix), but the forward decay of that
    # inhibitory mass over the horizon [t, t+H] is not modeled -- so the predictor
    # underestimates the rate at which exposure rises back toward background as old
    # applications wear off. This is documented in docs/section2_assumptions.md §A8.
    supp = np.zeros_like(times)
    # Suppression scales by q̂_a — effectiveness at application, before depletion jump.
    supp[after] = (q_hat * beta_c * dyn.kernel_self
                   * np.exp(-(times[after] - lead) / dyn.omega_u))

    # Integrated exposure mode (Plan §3.1 variant C objective): return exposure-
    # reduction integral directly without STL robustness computation.
    if dyn.valuation_mode == "integrated_exposure":
        reduction = np.minimum(e_nom_cell[after], supp[after])
        u = float(np.sum(reduction) * params.monitor_dt)
        return u if u > dyn.benefit_gate else 0.0

    # Continuation rollout mode (Plan §4): J_H(pi_0) - J_H(pi_a).
    if dyn.valuation_mode == "continuation_rollout":
        from habituation_stl.rollout import continuation_value, service_feasibility
        # Service protection check (Plan §4E): reject if a feasible reactive task is delayed.
        if dyn.service_protection:
            feasible = service_feasibility(
                action, list(cells), cell_states, hab, params, dyn,
                reactive_tasks=reactive_tasks,
                pending_events=fleet_pending_events if fleet_pending_events is not None else pending_events,
                n_robots=dyn.n_robots,
                avg_travel_s=dyn.avg_travel_s,
                service_hold_s=dyn.service_hold_s,
            )
            if not feasible:
                return 0.0
        u = continuation_value(
            action, list(cells), cell_states, hab, params, dyn,
            pending_events=pending_events,
            n_robots=dyn.n_robots,
            avg_travel_s=dyn.avg_travel_s,
            service_hold_s=dyn.service_hold_s,
            greedy_dt_s=dyn.greedy_dt_s,
        )
        return u if u > dyn.benefit_gate else 0.0

    # STL robustness mode (default).
    spec, _ = build_spec(cells, params, reactive_ids)
    nom_trace = Trace(times, nom)
    rho_nom = robustness_at(spec, nom_trace, 0)

    wa = _build_wa_signals(nom, a_cell, a_mode, lead, times, after,
                           q_hat, eta_post, e_nom_cell, supp, hab, dyn)
    wa_trace = Trace(times, wa)
    rho_wa = robustness_at(spec, wa_trace, 0)
    return float(rho_wa - rho_nom)


def robustness_breakdown(action, cells, cell_states, hab, params: SpecParams,
                         dyn: Dynamics, reactive_ids=None, pending_events=None):
    """Diagnostic: per-clause robustness for nom and wa traces.

    Returns a dict:
      'nom'               : {clause_name: rho} for the nominal trace
      'wa'                : {clause_name: rho} for the with-action trace
      'binding_clause_nom': clause name with the lowest nom robustness
      'binding_clause_wa' : clause name with the lowest wa robustness
      'U_stl'             : overall rho_wa - rho_nom (weighted conjunction)
      'U_ie'              : integrated exposure value (always computed)

    This function is used to diagnose which clause and time drives the score,
    and to verify whether masking (high e0 -> U_stl=0) is occurring while
    U_ie remains positive.
    """
    a_cell, a_mode, lead = int(action[0]), int(action[1]), float(action[2])
    times = _times(params)
    nom = _nominal_signals(cells, cell_states, times, dyn)
    e_nom_cell = nom[f"e_{a_cell}"]
    after = times >= lead

    q_hat, eta_post = _compute_q_hat(a_cell, a_mode, lead, hab, dyn, params, pending_events)

    beta_c = float(dyn.beta[a_mode]) if a_mode < len(dyn.beta) else float(dyn.beta[-1])
    supp = np.zeros_like(times)
    supp[after] = (q_hat * beta_c * dyn.kernel_self
                   * np.exp(-(times[after] - lead) / dyn.omega_u))

    nom_trace = Trace(times, nom)
    wa = _build_wa_signals(nom, a_cell, a_mode, lead, times, after,
                           q_hat, eta_post, e_nom_cell, supp, hab, dyn)
    wa_trace = Trace(times, wa)

    spec, clauses = build_spec(cells, params, reactive_ids)
    nom_rho = {name: float(robustness_at(clause, nom_trace, 0))
               for name, clause in clauses.items()}
    wa_rho = {name: float(robustness_at(clause, wa_trace, 0))
              for name, clause in clauses.items()}

    binding_nom = min(nom_rho, key=nom_rho.get) if nom_rho else None
    binding_wa = min(wa_rho, key=wa_rho.get) if wa_rho else None

    rho_nom = robustness_at(spec, nom_trace, 0)
    rho_wa = robustness_at(spec, wa_trace, 0)

    reduction = np.minimum(e_nom_cell[after], supp[after])
    u_ie = float(np.sum(reduction) * params.monitor_dt)

    return {
        "nom": nom_rho,
        "wa": wa_rho,
        "binding_clause_nom": binding_nom,
        "binding_clause_wa": binding_wa,
        "U_stl": float(rho_wa - rho_nom),
        "U_ie": u_ie,
    }


def cue_preservation_value(action, cells, cell_states, hab, params: SpecParams,
                            dyn: Dynamics, reactive_ids=None, pending_events=None):
    """Diagnostic: U with vs. without the effectiveness-floor (hab) clause.

    Returns (U_full, U_no_hab, hab_contribution).
      U_full         -- counterfactual_value with full active_clauses
      U_no_hab       -- counterfactual_value with hab clause removed
      hab_contribution -- U_full - U_no_hab; negative means the floor is
                          penalizing this action (depleted cue), positive means
                          the fresh-cue bonus exceeds the penalty.

    This diagnostic determines whether the effectiveness floor is binding
    (and by how much) vs. whether the exposure/coverage clauses dominate.
    """
    params_no_hab = replace(params,
                            active_clauses=tuple(c for c in params.active_clauses
                                                 if c != "hab"))
    u_full = counterfactual_value(action, cells, cell_states, hab, params, dyn,
                                   reactive_ids, pending_events)
    u_no_hab = counterfactual_value(action, cells, cell_states, hab, params_no_hab, dyn,
                                     reactive_ids, pending_events)
    return u_full, u_no_hab, u_full - u_no_hab


def best_action_for_cell(a_cell, cells, cell_states, hab, params: SpecParams,
                         dyn: Dynamics, completion_lead=60.0, reactive_ids=None,
                         pending_events=None):
    """Pick the cue mode maximizing U for a candidate cell; return (mode, U).

    The habituation clause makes this prefer un-habituated modes automatically.
    """
    best_m, best_u = 0, -np.inf
    for m in range(hab.n_modes):
        u = counterfactual_value((a_cell, m, completion_lead), cells, cell_states,
                                 hab, params, dyn, reactive_ids,
                                 pending_events=pending_events)
        if u > best_u:
            best_m, best_u = m, u
    return best_m, float(best_u)
