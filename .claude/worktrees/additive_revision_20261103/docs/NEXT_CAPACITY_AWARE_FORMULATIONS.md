# Next Capacity-Aware Formulations

## Purpose

This note defines the next simultaneous comparison package after the earlier
`res`, `res-soft`, `res-adaptive`, and lead-time experiments underperformed the
`unc` baseline.

The goal is to test whether predictive task claims improve when they are made:

- only for feasible future-event tasks,
- only when the robot and reactive queue can afford them,
- and with explicit use of predictive confidence.

## Shared Lead-Time Terms

For predictive tasks, define:

```text
s_pred = t_event - t_now - eta - tau_service
```

Where:

- `t_event` is the forecast event time,
- `t_now` is the current dispatch time,
- `eta` is predicted travel time,
- `tau_service` is the deterrence service time.

Interpretation:

- `s_pred >= 0` means the predictive task is still feasible,
- `s_pred < 0` means the robot is already too late.

We also define a simple reactive pressure proxy:

```text
q_react = N_react / (N_react + 1)
```

Where `N_react` is the number of reactive tasks currently competing for
dispatch.

## Confidence Term

The confidence-based formulations use:

```text
C_pred = clip(p_event * selection_weight, 0, 1)
```

This combines:

- `p_event`: estimated probability of a useful near-future bird event
- `selection_weight`: strength/persistence of the supporting predictive evidence

This makes predictive value depend on both expected gain and trust in that gain.

## Formulations

### 1. Feasible Reservation

Policy: `res-feasible`

Claim predictive only if:

```text
predictive_share < rho
and s_pred >= s_min
```

This tests whether simple deadline feasibility alone removes some of the wasted
predictive claims.

### 2. Idle + Feasible Reservation

Policy: `res-idle-feasible`

Claim predictive only if:

```text
predictive_share < rho
and robot_is_idle
and q_react <= q_max
and s_pred >= s_min
```

This makes reservation opportunistic instead of preemptive.

### 3. Confidence-Weighted Reservation

Policy: `res-confidence`

Keep reserved-capacity admission, but rank predictive tasks by:

```text
S_pred = predicted_deltaJ * C_pred + w_d * u_deadline - w_eta * eta
```

With:

```text
u_deadline = 1 / (1 + max(s_pred, 0))
```

This tests whether confidence-weighted predictive scoring improves which
predictive task is selected once capacity is reserved.

### 4. Idle + Feasible + Confidence Reservation

Policy: `res-idle-feasible-confidence`

Claim predictive only if:

```text
predictive_share < rho
and robot_is_idle
and q_react <= q_max
and s_pred >= s_min
and C_pred >= c_min
```

Then rank predictive tasks by:

```text
S_pred = predicted_deltaJ * C_pred + w_d * u_deadline - w_eta * eta
```

This is the most selective formulation in the comparison package.

## Defaults Used In The First Comparison

```text
rho = 0.25
s_min = 15 s
q_max = 0.5
c_min = 0.25
w_d = 2.0
w_eta = 0.1
```

Runtime parameters:

```python
predictive_slack_min_s = 15.0
reactive_pressure_max_for_predictive = 0.5
predictive_confidence_min = 0.25
predictive_deadline_weight = 2.0
predictive_eta_penalty_weight = 0.1
predictive_confidence_source = "p_event_times_selection_weight"
```

## Experimental Question

These formulations separate four hypotheses:

1. Does simple deadline feasibility help?
2. Does opportunistic idle-time reservation help?
3. Does explicit field confidence help?
4. Does combining feasibility, spare capacity, and confidence help more than any one factor alone?

The comparison should be run against `unc` using the same scenario, same seeds,
and the same predictive lead-time task-generation surface so only the dispatch
formulation changes.
