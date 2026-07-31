"""
mission_spec.py -- the habituation-aware STL mission specification.

Builds Phi = phi_exp ^ phi_react ^ phi_cov ^ phi_hab (Eq. 21) from the stl.py
AST, with each clause's predicate normalized by its threshold so the components
are scale-comparable under smooth conjunction (Sec. 5.4 / 5.5).

Clauses (per monitored cell z):
  phi_exp  : Always (e_z <= E*)                       (Eq. 22)
  phi_cov  : Always (g_z <= T_cov)                    (Eq. 24)
  phi_hab  : Always (active_z -> eta_z >= eta_min)    (Eq. 26, effectiveness-floor form)
  phi_react: Always (arr_a -> Eventually_[0,Treact] srv_a)  (Eq. 23, optional)

Signal naming convention expected on the Trace:
  e_{cell}    value-weighted exposure rate in the cell
  g_{cell}    seconds since the cell was last serviced (coverage age)
  eta_{cell}  effectiveness of the cue currently/last applied in the cell
              (set to 1.0 when no deterrence is active -> clause vacuously holds)
  arr_{aid}, srv_{aid}  reactive arrival / serviced indicators (optional)

The local sub-spec Phi_r for robot r is obtained by passing only that robot's
cells (Sec. 6.1).
"""
from __future__ import annotations

from dataclasses import dataclass, field

import numpy as np

from stl import (Aggregator, signal_leq, signal_geq, Implies, And,
                 Always, Eventually, Scale)


@dataclass
class SpecParams:
    E_star: float = 5.0        # exposure budget per cell (value-weighted rate)
    T_cov: float = 1200.0      # max seconds a cell may go unserviced
    T_react: float = 180.0     # reactive deadline (s)
    W: float = 600.0           # anti-habituation refractory window (s) [past-time form]
    eta_min: float = 0.4       # effectiveness floor
    horizon: float = 300.0     # robustness evaluation horizon H (s)
    monitor_dt: float = 30.0   # monitor / sampling period Delta_m (s)
    theta: float = 12.0        # smooth-robustness temperature
    smooth: bool = True        # use smooth (softmin/softmax) aggregation
    active_clauses: tuple = ("exp", "cov", "hab")  # which clauses are in Phi
    clause_weights: dict = field(default_factory=lambda: {
        "exp": 1.0, "cov": 1.0, "hab": 1.0, "react": 1.0})

    def aggregator(self) -> Aggregator:
        return Aggregator("smooth", self.theta) if self.smooth else Aggregator("classical")


def _cell_conjunction(cells, make_pred, agg):
    return And([make_pred(c) for c in cells], agg=agg)


def build_clauses(cells, params: SpecParams, reactive_ids=None):
    """Return a dict of the individual clause formulas over `cells`.

    Each clause is evaluated as Always over [0, horizon]; robustness_at(t=0)
    then yields the worst-case margin across the evaluation window.
    """
    agg = params.aggregator()
    H = params.horizon

    # phi_exp: e_z <= E*  (normalized by E*)
    exp_inner = _cell_conjunction(
        cells, lambda c: signal_leq(f"e_{c}", params.E_star, scale=params.E_star,
                                    label=f"e_{c}<=E*"), agg)
    phi_exp = Always(exp_inner, 0.0, H, agg=agg)

    # phi_cov: g_z <= T_cov  (normalized by T_cov)
    cov_inner = _cell_conjunction(
        cells, lambda c: signal_leq(f"g_{c}", params.T_cov, scale=params.T_cov,
                                    label=f"g_{c}<=T_cov"), agg)
    phi_cov = Always(cov_inner, 0.0, H, agg=agg)

    # phi_hab: eta_z >= eta_min  (normalized by 1 - eta_min)
    hab_inner = _cell_conjunction(
        cells, lambda c: signal_geq(f"eta_{c}", params.eta_min,
                                    scale=(1.0 - params.eta_min),
                                    label=f"eta_{c}>=eta_min"), agg)
    phi_hab = Always(hab_inner, 0.0, H, agg=agg)

    clauses = {}
    if "exp" in params.active_clauses:
        clauses["exp"] = phi_exp
    if "cov" in params.active_clauses:
        clauses["cov"] = phi_cov
    if "hab" in params.active_clauses:
        clauses["hab"] = phi_hab

    # phi_react (optional): for each open reactive task, arrival implies service
    # within the deadline. Robustness normalized by T_react via the slack signal.
    if reactive_ids:
        react_terms = []
        for aid in reactive_ids:
            arr = signal_geq(f"arr_{aid}", 0.0, label=f"arr_{aid}")
            srv = signal_geq(f"srv_{aid}", 0.0, label=f"srv_{aid}")
            react_terms.append(Implies(arr, Eventually(srv, 0.0, params.T_react, agg=agg), agg=agg))
        phi_react = Always(And(react_terms, agg=agg), 0.0, H, agg=agg)
        clauses["react"] = phi_react

    return clauses


def build_inner_clauses(cells, params: SpecParams):
    """Non-temporal per-cell conjunctions for the online monitor.

    Returns dict {clause -> Formula} where each formula is the cell conjunction
    of the normalized predicate (no Always wrapper). The online monitor takes
    the min over the trailing buffer = "held historically so far" robustness.
    """
    agg = params.aggregator()
    out = {}
    if "exp" in params.active_clauses:
        out["exp"] = _cell_conjunction(
            cells, lambda c: signal_leq(f"e_{c}", params.E_star, scale=params.E_star), agg)
    if "cov" in params.active_clauses:
        out["cov"] = _cell_conjunction(
            cells, lambda c: signal_leq(f"g_{c}", params.T_cov, scale=params.T_cov), agg)
    if "hab" in params.active_clauses:
        out["hab"] = _cell_conjunction(
            cells, lambda c: signal_geq(f"eta_{c}", params.eta_min,
                                        scale=(1.0 - params.eta_min)), agg)
    return out


def _weighted_clause_formula(name, formula, params: SpecParams):
    """Return a clause formula with the configured robustness weight applied."""
    try:
        weight = float((params.clause_weights or {}).get(name, 1.0))
    except Exception:
        weight = 1.0
    if not np.isfinite(weight) or weight <= 0.0:
        weight = 1.0
    if abs(weight - 1.0) <= 1e-12:
        return formula
    return Scale(formula, weight)


def build_spec(cells, params: SpecParams, reactive_ids=None):
    """Return (global_spec, clause_dict). global_spec = weighted conjunction.

    Clause weights scale each normalized clause robustness before conjunction,
    allowing the planner to make a selected clause more or less likely to bind.
    The returned clause dictionary remains unweighted for diagnostics.
    """
    agg = params.aggregator()
    clauses = build_clauses(cells, params, reactive_ids)
    weighted_clauses = [
        _weighted_clause_formula(name, formula, params)
        for name, formula in clauses.items()
    ]
    spec = And(weighted_clauses, agg=agg)
    return spec, clauses
