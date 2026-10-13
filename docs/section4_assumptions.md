# Section 4 Implementation Assumptions

## Overview

Section 4 replaces the integrated-exposure valuation with a continuation rollout
that models subsequent greedy robot interventions.  The objective is:

    U(a) = J_H(pi_0) - J_H(pi_a)
    J_H   = integral_0^H sum_z e_z(s) ds  under greedy continuation policy pi

A positive U(a) means the candidate action reduces net accumulated exposure over
the horizon compared to taking no predictive action.

## Approximations

### A4.1 -- Constant travel time

All robot-to-cell travel times are approximated as the scalar `avg_travel_s`
(default 30 s).  Actual travel varies by robot position and cell location.
The constant-travel approximation is conservative: cells that are closer than
avg_travel_s will be served sooner, so the true benefit of intervention is at
least as large as computed.

### A4.2 -- Greedy intervention mode

Default (`rollout_cue_dynamics=False`): subsequent greedy interventions always use
mode 0 effectiveness from the hab snapshot at planning time, with suppression
strength `beta[0]`.  Mode selection is not simulated per step.

With `rollout_cue_dynamics=True` (Plan Section 3, "value future cue use"): each
greedy intervention picks the mode maximizing `eta(c, m) * beta[m]` on the
rollout's habituation copy, evaluated at its own application time
`apply_t = t_assign + avg_travel_s`, and suppresses with that mode's `q = eta(c, m)`
and `beta[m]`.  This is a myopic per-intervention rule (best cue now), not an
optimization over the rest of the rollout; it mirrors a variety-seeking executor
rather than the planner's own STL-scored mode choice.

### A4.3 -- Habituation state inside the rollout

Default (`rollout_cue_dynamics=False`): habituation is frozen.  The hab object is
the snapshot at the moment of planning; neither pending events, the candidate, nor
greedy interventions deplete it, and no recovery is modeled between steps.  The
candidate's own q_hat still comes from `_compute_q_hat` (which, under
`forecast_correction`, accounts for pending events and travel-time recovery).
Because repeated cues are never depleted, the frozen rollout cannot see that a
candidate consumes a fresh cue the continuation would later need, so U(a) is
blind to the value of preserving a cue.

With `rollout_cue_dynamics=True`: the rollout works on `hab.copy()` (the live
object is never mutated) and processes events chronologically through a
time-ordered queue:

* known pending events `(rel_t, cell, mode)` deplete their cue at `rel_t`;
* the candidate suppresses with q_hat from `_compute_q_hat` and depletes
  `(cell, mode)` at `lead`;
* each greedy intervention is assigned at a step time but resolved at its
  `apply_t`: the copy is recovered to `apply_t` (after all earlier applications),
  the mode and q are read, the suppression is added, and the cue is depleted with
  `hab.apply(c, m)` (including cross-mode generalization when `gamma > 0`);
* recovery between events uses `hab.recover(dt)` (Eq. 6).

Applications are resolved lazily, just before the exposure sample they can affect
is read (any event with time <= the grid time read at a greedy step).

Remaining approximations under the flag:

* Travel is still the constant `avg_travel_s` (A4.1), so application times are
  approximate and every greedy intervention lands exactly `avg_travel_s` after
  assignment.
* Pending events only deplete cues; their suppression is not added to the
  rollout exposure (unchanged from the default, which ignores them entirely
  apart from robot availability).
* The candidate's q_hat is computed from the live hab by `_compute_q_hat`, not
  from the rollout copy.  With `forecast_correction=True` the two agree (same
  pending events, same recovery); with it off, q_hat is the decision-time eta.
* Suppressions on the same cell are still independent and additive in effect
  (A4.4): no overlap or saturation between them.
* If a greedy step falls within half a monitor period of an application time,
  that application may be resolved one step early relative to a later-assigned
  intervention; with the default `avg_travel_s=30` and `monitor_dt=30` this
  ordering slip cannot occur for greedy interventions (apply_t - t_assign = 30 s
  > monitor_dt / 2), and recovery is never run backward.

### A4.4 -- Analytic exposure trajectories

Cell exposure between greedy steps is evaluated from the analytic nominal signal
updated by suppressions that have already been applied in this rollout.  This is
the same analytic model used by the STL monitor and the integrated-exposure
objective.  Interaction between suppressions (two robots acting on the same cell
at overlapping times) is not modeled; each suppression is computed independently.

## Service Protection (Plan §4E)

The service protection filter (variant E) checks feasibility under the baseline
robot availability, then verifies that committing one robot to the candidate action
for `lead_s` seconds does not prevent any already-feasible reactive task from
being served.

A reactive task with deadline `d` is feasible when at least one robot is free
at or before `d - avg_travel_s`.  The filter rejects the candidate if any such
task becomes infeasible under the candidate robot commitment.

The filter is conservative: it uses the same constant `avg_travel_s` as the
rollout (A4.1).

## Parameters

| Parameter | Default | Description |
|---|---|---|
| `n_robots` | 4 | Total number of robots |
| `avg_travel_s` | 30.0 | Constant travel time to any cell (s) |
| `service_hold_s` | 20.0 | Time a robot holds at a cell after arrival (s) |
| `greedy_dt_s` | 45.0 | Greedy assignment interval (s); matches task_replan_period_s |
| `benefit_gate` | 0.0 | Minimum U(a) to admit action; 0 = admit any positive-benefit action |
| `service_protection` | False | If True, enable Plan §4E service feasibility filter |
| `rollout_cue_dynamics` | False | If True, carry cue depletion and recovery through the rollout and choose greedy modes per intervention (A4.2, A4.3); DeterrentSystem kwarg `stl_rollout_cue_dynamics` |
