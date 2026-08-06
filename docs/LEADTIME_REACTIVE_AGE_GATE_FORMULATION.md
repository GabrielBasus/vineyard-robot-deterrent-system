# Lead-Time Reactive-Age Gate Formulation

## Purpose

This note documents the first mathematical adjustment applied after the original
capacity-aware and lead-time formulations were evaluated:

- keep predictive lead-time task generation
- add a stronger reactive-age gate to the adaptive reservation policy

The goal is to preserve the exposure benefit of predictive tasking while reducing
the two main failure modes seen in the earlier comparisons:

- large reactive response delays
- too many urgent reactive overrides

## Baselines

The comparison now has three relevant capacity-aware variants:

- `res_0p25`
  Original hard reservation policy.
- `res_0p25_leadtime`
  Original reservation policy with predictive lead-time release.
- `res_adaptive_leadtime_0p25`
  Lead-time release plus adaptive reservation shrinkage and a tighter reactive-age gate.

The greedy reference remains:

- `unc`

## Predictive Lead-Time Formulation

For preventive tasks, we treat task generation as targeting a future bird-event
time rather than only the current hotspot time.

Let:

- `t_now` be the current planning time
- `eta` be estimated travel time to the task
- `tau_service` be deterrence service time
- `T_replan` be the replanning interval
- `b` be a small safety buffer

The required intervention horizon is:

```text
L_req = T_replan + eta + tau_service + b
```

We then define a bounded lead time:

```text
L_min <= L <= L_max
```

with:

```text
L_max = T_replan + ETA_max + tau_service + b
```

The task’s future event time becomes:

```text
t_event = t_now + L
```

and the task is treated as requiring arrival by:

```text
t_arrive_by = t_event
```

The predictive timing slack used for diagnostics is:

```text
s_pred = t_event - t_now - eta - tau_service
```

So:

- `s_pred > 0` means the preventive action is still feasible before the forecast event
- `s_pred < 0` means the preventive action is already too late

## Reactive-Age-Gated Reservation

The original hard reservation policy was approximately:

```text
claim predictive if predictive_share < rho
```

That was too aggressive, because it could still protect predictive work while
reactive detections were aging.

The adaptive reservation target is:

```text
rho_eff = rho / (1 + alpha * p_react + beta * a_react)
```

Where:

- `rho` is the nominal reserved predictive fraction
- `alpha` is `reservation_softening_alpha`
- `beta` is `reservation_age_softening_beta`
- `p_react = N_react / (N_react + N_pred)` is reactive competition pressure
- `a_react = A_max / tau_exp`

and:

- `A_max` is the age of the oldest reactive task
- `tau_exp` is the reactive override slack horizon

This means the reserved predictive target shrinks as:

- more reactive tasks compete with predictive tasks
- the oldest reactive task gets closer to the urgent-override boundary

## Reactive-Age Gate

We then add a hard claim gate:

```text
claim predictive only if
predictive_share < rho_eff
and a_react < gamma_age
```

Where:

- `gamma_age` is `reservation_age_gate`

This is the key new adjustment.

It says:

- even if the robot is below its predictive-share target,
- predictive work is blocked once reactive waiting age grows too much.

## Parameterization Used

The new profile `res_adaptive_leadtime_0p25` uses:

```text
rho = 0.25
alpha = 2.0
beta = 5.0
gamma_age = 0.25
L_min = 30 s
ETA_max = 120 s
buffer = 15 s
```

In runtime terms:

```python
dispatch_policy="res-adaptive"
reservation_fraction=0.25
reservation_softening_alpha=2.0
reservation_age_softening_beta=5.0
reservation_age_gate=0.25
enable_predictive_lead_time=True
predictive_lead_time_min_s=30.0
predictive_lead_time_max_eta_s=120.0
predictive_lead_time_buffer_s=15.0
predictive_lead_time_risk_power=1.0
```

## Interpretation

This formulation is intended to be easier to defend mathematically than the
original hard reservation rule:

1. preventive tasks now represent future opportunity, not just current field intensity
2. reservation shrinks smoothly under reactive pressure
3. predictive claims are blocked once reactive age becomes meaningfully unsafe

The thesis question is now narrower and clearer:

> Does predictive lead-time plus reactive-age-gated reservation outperform the
> older capacity-aware formulations, and can it close the gap to `unc`?

## Files

- [DeterrentSystem.py](/c:/Users/gabri/Documents/CalPoly/Thesis/Code/DeterrentSystem.py)
  Runtime dispatch already contained the adaptive reservation equation and age gate.
- [TaskGenerator.py](/c:/Users/gabri/Documents/CalPoly/Thesis/Code/TaskGenerator.py)
  Predictive tasks now carry future event timing and lead-time fields.
- [planner_profiles.py](/c:/Users/gabri/Documents/CalPoly/Thesis/Code/planner_profiles.py)
  Added `res_adaptive_leadtime_0p25`.

## Test Command

Smoke comparison:

```powershell
python -m experiments.run_capacity_leadtime_compare --config testbench\thesis_compare_unc_vs_leadtime_vs_agegate_smoke.json --max-workers 1
```

24-hour nominal comparison:

```powershell
python -m experiments.run_capacity_leadtime_compare --config testbench\thesis_compare_unc_vs_leadtime_vs_agegate_nominal_24h.json --max-workers 1
```
