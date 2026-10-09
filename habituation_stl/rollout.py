"""
rollout.py -- deterministic greedy continuation rollout for Plan §4.

Implements U(a) = J_H(pi_0) - J_H(pi_a) where J_H is accumulated exposure
under a greedy continuation policy (Plan Eq. 3).

Algorithm
---------
Both rollouts (baseline and candidate) use the analytic forward predictor from
task_value.py for cell exposure trajectories.  On top of that, a discrete-event
greedy scheduler models subsequent robot interventions within the horizon:

  1. At each greedy step (every greedy_dt_s), free robots are assigned to the
     highest-exposure unserviced cells in decreasing order.
  2. Each assigned robot becomes busy for avg_travel_s + service_hold_s.
  3. When a robot completes, it applies suppression to its target cell and
     rejoins the free pool.
  4. J_H is accumulated as sum_z e_z(t) * dt at each greedy step.

For the candidate rollout, one robot is committed to the candidate action for
lead_s seconds before joining the greedy pool.  This captures the capacity
cost: a robot occupied with a predictive action cannot serve other cells during
that time.

Approximations (documented in docs/section4_assumptions.md):
  A4.1 -- Travel time is a constant avg_travel_s for all cells.
  A4.2 -- The greedy policy always uses the best available cue mode (mode 0
           if hab is not available, otherwise best_mode_for_cell).
  A4.3 -- Subsequent greedy interventions do not update hab between steps;
           effectiveness is estimated from the snapshot at planning time.
  A4.4 -- Cell exposure at each greedy step is evaluated from the analytic
           trajectory, updated by previous suppressions in this rollout.
"""
from __future__ import annotations

import heapq
from typing import Optional

import numpy as np

from habituation_stl.task_value import (
    Dynamics,
    CellState,
    _times,
    _nominal_signals,
    _compute_q_hat,
    _build_wa_signals,
)
from habituation_stl.mission_spec import SpecParams


def _apply_suppression_to_signal(e_sig, times, lead, q_hat, beta_c, kernel_self, omega_u):
    """Return a new exposure array with suppression applied from `lead` onward."""
    after = times >= lead
    supp = np.zeros_like(times)
    supp[after] = (q_hat * beta_c * kernel_self
                   * np.exp(-(times[after] - lead) / omega_u))
    return np.maximum(0.0, e_sig - np.minimum(e_sig, supp))


def _robot_free_times(pending_events, n_robots):
    """Estimate robot free-at times from pending deterrence events.

    pending_events : [(rel_completion_s, cell_id, mode_id), ...]
    Returns a sorted list of length n_robots; robots without a pending task
    are free at t=0.
    """
    busy_times = sorted(float(e[0]) for e in (pending_events or []))[:n_robots]
    n_free = max(0, n_robots - len(busy_times))
    return sorted([0.0] * n_free + busy_times)


def greedy_rollout(
    cells: list,
    cell_states: dict,
    hab,
    params: SpecParams,
    dyn: Dynamics,
    candidate=None,
    pending_events=None,
    n_robots: int = 4,
    avg_travel_s: float = 30.0,
    service_hold_s: float = 20.0,
    greedy_dt_s: float = 45.0,
) -> float:
    """Return J_H = integral_0^H sum_z e_z(s) ds under the greedy continuation.

    candidate : (cell_id, mode_id, lead_s) or None for the baseline.
    When candidate is given, one robot is committed to it for lead_s seconds
    before joining the greedy pool.  All other robots follow the greedy policy.
    """
    times = _times(params)
    H = float(params.horizon)
    dt = float(params.monitor_dt)
    beta_c = float(dyn.beta[0]) if dyn.beta else 1.0

    # Analytic nominal signals for all cells.
    nom = _nominal_signals(cells, cell_states, times, dyn)
    # Mutable copy of each cell's exposure array (will be updated as suppressions land).
    e_sig = {c: nom[f"e_{c}"].copy() for c in cells}

    # Robot free-at times (heap, in seconds from now).
    robot_free = _robot_free_times(pending_events, n_robots)

    # If candidate, apply its suppression and commit one robot.
    if candidate is not None:
        a_cell, a_mode, lead = int(candidate[0]), int(candidate[1]), float(candidate[2])
        q_hat, _ = _compute_q_hat(a_cell, a_mode, lead, hab, dyn, params, pending_events)
        beta_m = float(dyn.beta[a_mode]) if a_mode < len(dyn.beta) else beta_c
        e_sig[a_cell] = _apply_suppression_to_signal(
            e_sig[a_cell], times, lead, q_hat, beta_m, dyn.kernel_self, dyn.omega_u)
        # Consume the first available robot; it becomes free at lead.
        if robot_free:
            robot_free[0] = max(robot_free[0], lead)
        else:
            robot_free = [lead]
        heapq.heapify(robot_free)

    heapq.heapify(robot_free)

    # Track which cells are being serviced and when they become unserviced.
    # cell -> next_free_at (time when the cell's robot leaves).
    cell_busy_until: dict[int, float] = {}

    j_cost = 0.0
    t_prev = 0.0

    for step_idx in range(int(H / greedy_dt_s) + 1):
        t = min(step_idx * greedy_dt_s, H)

        # Accumulate J_H from t_prev to t using exposure at t_prev.
        if t > t_prev:
            ti = min(int(round(t_prev / dt)), len(times) - 1)
            for c in cells:
                j_cost += float(e_sig[c][ti]) * (t - t_prev)
            t_prev = t

        if t >= H:
            break

        # Release robots that have completed their tasks by time t.
        for c in list(cell_busy_until):
            if cell_busy_until[c] <= t:
                del cell_busy_until[c]

        # Identify cells not currently serviced, sorted by descending exposure at t.
        ti = min(int(round(t / dt)), len(times) - 1)
        unserviced = sorted(
            [c for c in cells if c not in cell_busy_until],
            key=lambda c: -float(e_sig[c][ti]),
        )

        # Assign free robots greedily.
        for c in unserviced:
            if not robot_free:
                break
            free_t = heapq.heappop(robot_free)
            if free_t > t:
                heapq.heappush(robot_free, free_t)
                break
            # Assign this robot to cell c.
            travel_complete = t + avg_travel_s
            apply_t = travel_complete
            release_t = apply_t + service_hold_s
            cell_busy_until[c] = release_t
            heapq.heappush(robot_free, release_t)

            # Apply suppression to e_sig[c] from apply_t onward.
            q = float(hab.effectiveness(c, 0)) if hab is not None else 1.0
            e_sig[c] = _apply_suppression_to_signal(
                e_sig[c], times, apply_t, q, beta_c, dyn.kernel_self, dyn.omega_u)

    return j_cost


def continuation_value(
    action,
    cells: list,
    cell_states: dict,
    hab,
    params: SpecParams,
    dyn: Dynamics,
    pending_events=None,
    n_robots: int = 4,
    avg_travel_s: float = 30.0,
    service_hold_s: float = 20.0,
    greedy_dt_s: float = 45.0,
) -> float:
    """U(a) = J_H(pi_0) - J_H(pi_a) via the greedy rollout (Plan §4 Eq. 5).

    A positive value means the candidate action reduces net accumulated exposure.
    """
    j_baseline = greedy_rollout(
        cells, cell_states, hab, params, dyn,
        candidate=None,
        pending_events=pending_events,
        n_robots=n_robots,
        avg_travel_s=avg_travel_s,
        service_hold_s=service_hold_s,
        greedy_dt_s=greedy_dt_s,
    )
    j_candidate = greedy_rollout(
        cells, cell_states, hab, params, dyn,
        candidate=action,
        pending_events=pending_events,
        n_robots=n_robots,
        avg_travel_s=avg_travel_s,
        service_hold_s=service_hold_s,
        greedy_dt_s=greedy_dt_s,
    )
    return j_baseline - j_candidate


def service_feasibility(
    action,
    cells: list,
    cell_states: dict,
    hab,
    params: SpecParams,
    dyn: Dynamics,
    reactive_tasks: list | None = None,
    pending_events=None,
    n_robots: int = 4,
    avg_travel_s: float = 30.0,
    service_hold_s: float = 20.0,
) -> bool:
    """Return True if the candidate action does not delay any feasible reactive task.

    Plan §4: F_0 = {j : C_hat_j(pi_0) <= d_j}.  Admit candidate only when
    C_hat_j(pi_cand) <= d_j for all j in F_0.

    reactive_tasks : list of dicts with keys "deadline_s" (relative to now) and
                     "min_robots_needed" (default 1).  A task is feasible under
                     the baseline when at least one robot can reach it within
                     deadline_s (i.e., deadline_s >= avg_travel_s + service_hold_s).
    """
    if not reactive_tasks:
        return True

    a_cell, a_mode, lead = int(action[0]), int(action[1]), float(action[2])
    robot_free_base = _robot_free_times(pending_events, n_robots)
    # Under the candidate, one robot is busy until lead.
    robot_free_cand = list(robot_free_base)
    if robot_free_cand:
        robot_free_cand[0] = max(robot_free_cand[0], lead)
    else:
        robot_free_cand = [lead]
    robot_free_cand.sort()

    for task in reactive_tasks:
        deadline = float(task.get("deadline_s", float("inf")))
        min_resp = float(avg_travel_s + service_hold_s)
        # Feasible under baseline: any robot free before deadline - avg_travel_s.
        feasible_base = any(t <= deadline - avg_travel_s for t in robot_free_base)
        if not feasible_base:
            continue  # not in F_0; skip
        # Must remain feasible under candidate.
        feasible_cand = any(t <= deadline - avg_travel_s for t in robot_free_cand)
        if not feasible_cand:
            return False

    return True
