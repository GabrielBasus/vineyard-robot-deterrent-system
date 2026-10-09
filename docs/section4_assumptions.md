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

### A4.2 -- Mode-0 greedy interventions

Subsequent greedy interventions always use mode 0 effectiveness from the hab
snapshot at planning time.  The planner does not simulate mode selection at each
future step, since the chosen mode depends on future robot and cell state that is
unknown at planning time.

### A4.3 -- Frozen habituation state

Habituation state is not updated between greedy steps.  The hab object is the
snapshot at the moment of planning.  Future interventions will in practice update
hab, but predicting those updates requires a full forward simulation.  This
approximation means the model slightly underestimates effectiveness of later
interventions (overstates J_H), making the valuation conservative.

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
