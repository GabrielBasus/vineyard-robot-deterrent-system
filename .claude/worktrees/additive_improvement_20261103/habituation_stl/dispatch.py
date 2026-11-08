"""
dispatch.py -- reserved-capacity dispatch with robustness value (Algorithm 3).

This is the existing reserved-capacity dispatcher from the April reframe, with
the predictive utility replaced by the counterfactual robustness value U(a, r)
(task_value.counterfactual_value). The dispatcher logic is otherwise unchanged:
a soft per-window reservation rho for predictive work, with a hard-latency
override that always protects an imminent reactive deadline.

Task dicts:
  reactive : {"id", "value", "t_exp", "target_cell", ...}
  predictive: {"id", "cell", "mode", "completion_lead", ...} plus a precomputed
              "U" value (or pass value_fn to compute it on demand).
"""
from __future__ import annotations


def reserved_capacity_dispatch(t, queue_reactive, queue_predictive,
                               phi_pred_frac, rho, tau_exp,
                               value_fn=None):
    """Return the selected task dict (with a 'decision' tag) or None for idle.

    Parameters
    ----------
    t               : current time (s)
    queue_reactive  : list of reactive task dicts in this robot's queue
    queue_predictive: list of predictive task dicts in this robot's queue
    phi_pred_frac   : sliding-window predictive time fraction phi = t_pred / T_W
    rho             : reservation fraction in [0, 1]
    tau_exp         : hard-latency bound (s)
    value_fn        : optional fn(pred_task) -> U; if None, uses task["U"]
    """
    def U(task):
        if value_fn is not None:
            return value_fn(task)
        return float(task.get("U", 0.0))

    # (1) hard-latency override: protect an imminent reactive deadline.
    if queue_reactive:
        a_urgent = min(queue_reactive, key=lambda a: a["t_exp"] - t)
        if (a_urgent["t_exp"] - t) <= tau_exp:
            return {**a_urgent, "decision": "reactive_override"}

    # (2) reservation claim: if under predictive budget, take best predictive.
    if phi_pred_frac < rho and queue_predictive:
        a = max(queue_predictive, key=U)
        return {**a, "decision": "reservation_claim"}

    # (3) reactive service: highest-value reactive task.
    if queue_reactive:
        a = max(queue_reactive, key=lambda a: a["value"])
        return {**a, "decision": "reactive_service"}

    # (4) opportunistic predictive: idle capacity spent on best predictive.
    if queue_predictive:
        a = max(queue_predictive, key=U)
        return {**a, "decision": "opportunistic"}

    return None
