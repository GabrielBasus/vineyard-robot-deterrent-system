# Section 2 Implementation Assumptions

**Proposal**: "Make the forecast consistent with the intervention dynamics"
**Branch**: `thesis-improvement`
**Last updated**: 2026-10-05

This document records every assumption made in the Section 2 implementation so that
deviations from the equations are explicit, their practical impact is understood, and
any future reader can audit the code against the plan without rediscovering them.

---

## A1. δ_a includes travel time and service hold time

**Equation reference**: δ_a in Eq. (1).

**Assumption**: the application event is defined as service completion, so
δ_a = remaining_travel_time + hold_time_s.

**Where**: `TaskGenerator.py`, `completion_lead_s` computation. `task_value.py`,
`lead` argument to `counterfactual_value()`.

**Consequence**: if the simulator were changed to stamp suppression at arrival (before
the hold) rather than at completion, δ_a would need to drop the hold term.

---

## A2. Planner parameters T̂_rec and κ̂ are point estimates from planner_hab

**Equation reference**: T̂_rec in Eq. (1), κ̂ in Eq. (2).

**Assumption**: `hab` passed to `counterfactual_value()` is always `planner_hab`, the
planner's HabituationField. Its `T_rec` and `kappa` arrays are used as the planner's
parameter estimates with no uncertainty or confidence interval.

**Where**: `DeterrentSystem.py` line ~4081 (`Dynamics(forecast_correction=...)`),
`planner_task_estimation.py` `estimate_stl_counterfactual_value()`.

**Consequence**: if truth parameters drift significantly from the planner's calibrated
estimates, q̂_a will be biased. Parameter estimation is outside the scope of Section 2.

---

## A3. Centralized task visibility -- all robots' pending tasks are known

**Equation reference**: "Known intervening applications" in item 2.3.

**Assumption**: the system uses a centralized planner with full visibility over all
active tasks. `_stl_pending_events_by_robot()` therefore iterates all `active_tasks`
regardless of `assigned_primary`, giving every robot's candidate evaluation the
complete pool of pending deterrence completions.

**Where**: `DeterrentSystem.py`, `_stl_pending_events_by_robot()`.

**Consequence**: in a decentralized architecture where robot r can observe only its
own commitments, the pool must be restricted to that robot's own tasks. Under the
current centralized design the full-pool assumption is correct.

---

## A4. No cross-cell habituation coupling (gamma = 0 default)

**Equation reference**: Eq. (1) applies to a specific (cell, mode) pair.

**Assumption**: the default configuration uses `gamma = 0` in `HabituationField`,
meaning an application in cell A has no effect on cell B's η. Under this assumption,
pending events in cells other than the candidate cell do not affect q̂_a for that
candidate, so the cross-robot pending events from A3 have zero practical effect on
q̂_a (recovery advances globally, but depletion is cell-local).

**Where**: `habituation_stl/habituation.py`, `HabituationField.apply()`.

**Consequence**: if gamma > 0 is enabled, cross-cell coupling is active and
pending events in ANY cell will affect q̂_a for the candidate cell via the hab copy.
The code handles this correctly because `hab_fc.apply(c_ev, m_ev)` uses the same
`apply()` routine that respects gamma. No code change is required for gamma > 0.

---

## A5. Service time for pending tasks falls back to tau_service_s on error

**Equation reference**: δ_a = travel + hold, where hold = service time.

**Assumption**: if `task_action_service_time_s()` raises an exception for a pending
task (e.g., missing mode configuration), the service time defaults to `tau_service_s`
(the global service time parameter).

**Where**: `DeterrentSystem.py`, `_stl_pending_events_by_robot()` try/except block.

**Consequence**: rare; only applies to misconfigured tasks. The effect is a slightly
incorrect completion timestamp for that pending event, causing a small error in q̂_a
for the candidate robot's candidate. The fallback is acceptable for robustness.

---

## A6. Cell lookup for pending tasks uses _cell_id_for_xy at task (x, y)

**Equation reference**: pending event = (rel_t, cell_id, mode_id).

**Assumption**: the target cell of a pending deterrence task is determined by mapping
the task's stored `(x, y)` coordinates through `_cell_id_for_xy`. Tasks with
coordinates outside any cell polygon, or for which `_cell_id_for_xy` raises, are
silently dropped from the pending event list.

**Where**: `DeterrentSystem.py`, `_stl_pending_events_by_robot()`.

**Consequence**: tasks near cell boundaries may be dropped if the coordinate falls
outside every polygon. This is a minor data-quality issue, not a systematic bias.

---

## A7. Historical suppression uses planner eta at application time (pre-depletion)

**Equation reference**: û_r(x, t+s) = Σ_{j} q̂_j β_{c_j} K(x−x_j) e^{−(t+s−τ_j)/ω_u}

**Assumption**: `planner_eta_at_apply = planner_hab.effectiveness(cell_id, mode_idx)`
is read immediately before `_apply_habituation_update(planner_hab, ...)`. This is the
planner's η estimate at the moment of application (pre-depletion), used as q̂_j to
weight the suppression amplitude stamped into the planner's SESTPP model.

**Where**: `DeterrentSystem.py`, historical suppression block (~line 6350).

**Consequence**: the planner's SESTPP inhibitory amplitude for each past event is
q̂_j * β, which is the plan's Eq. for û_r. If `planner_hab` diverges from truth η
(parameter mismatch or delayed observation), the inhibitory amplitude in the planner
model will differ from truth, biasing the e0 snapshot at the next planning episode.

---

## A8. Forward trajectory correction -- implemented as variant C flag

**Equation reference**: nominal signal e_nom used in U(a,r).

**Status**: IMPLEMENTED and measurable. `Dynamics.forward_trajectory_correction=True`
(variant C) activates the corrected forward trajectory. Variant B leaves this off.
The A/B/C comparison experiment (`experiments/run_variant_ab_comparison.py`) runs
both and reports the incremental effect of this correction (C vs B delta).

**What the corrected formula does**: propagates the three components of the SESTPP
intensity separately over the planning horizon instead of collapsing to e0*exp(-s/omega_e):

```
e_nom_corrected(s) = mu0_t + trigger0 * exp(-s/omega_e) - inhib0 * exp(-s/omega_u)
```

where:
- `mu0_t = cell_integrated(model.mu) * time_multiplier(t_now)` (background, treated
  as constant over the short horizon -- circadian variation over H=300s is small)
- `trigger0 = cell_integrated(model.trigger_mass)`
- `inhib0 = cell_integrated(model.inhib_mass)` (total across all modes)

**Key physical effect**: when `inhib0` is large (heavy past suppression) and
`omega_u > omega_e` (inhibitory decay slower than trigger decay), the corrected e_nom
can RISE over the horizon as background dominates once inhibitory mass wears off. The
collapsed formula (`e0 * exp(-s/omega_e)`) always decays toward 0 and misses this
rebound. A rising e_nom can violate the exposure clause at interior horizon times even
when the snapshot e0 < E_star, changing rho_nom and therefore U.

**Where**: `task_value.py` `_nominal_signals()`, `planner_task_estimation.py` states
loop, `DeterrentSystem.py` `stl_forward_trajectory_correction` parameter.

**Remaining approximation within variant C**: the background term `mu0_t` is treated
as constant over the horizon. The true background is `mu0 * time_multiplier(t+s)`,
which has circadian variation (amplitude ±0.4 over 24h). Over H=300s, this variation
is at most a few percent and is acceptable for the planning horizon length used.

---

## A9. stl_travel_recovery_delta diagnostic -- variant A reports zero

**Equation reference**: stl_travel_recovery_delta = q̂_a - η(t).

**Assumption**: for variant A (`forecast_correction=False`), q̂_a = η(t) (no
travel-recovery correction applied), so `stl_travel_recovery_delta = 0` and
`stl_eta_at_apply = eta_now`. This is correct because the diagnostic reports the
magnitude of the correction that was ACTUALLY applied, not a counterfactual.

For variant B (`forecast_correction=True`), the diagnostic processes pending events
through a hab copy identically to `counterfactual_value()`, so `stl_travel_recovery_delta`
reports the exact q̂_a - η(t) used in the computation.

**Where**: `planner_task_estimation.py`, diagnostic block before the
`counterfactual_value()` call.

---

## A10. best_action_for_cell passes pending_events through to counterfactual_value

**Assumption**: `best_action_for_cell()` accepts an optional `pending_events`
parameter and threads it to every `counterfactual_value()` call inside the mode
selection loop. Callers that do not supply `pending_events` (the default `None`)
get variant A behavior regardless of `forecast_correction`, because an empty event
list produces the same q̂_a = 1-(1-η)*exp(-lead/T_rec) as the simple formula.

**Where**: `task_value.py`, `best_action_for_cell()`.

**Note**: this function is used only in `reference_sim.py` (standalone reference
simulator) and `run_demo.py`. Production task selection goes through
`planner_task_estimation.estimate_stl_counterfactual_value()` in `TaskGenerator.py`,
which is separately wired.

---

## A11. Variant A behavior is preserved exactly when forecast_correction = False

**Assumption**: every Section 2 correction is gated behind `dyn.forecast_correction`.
When `False`:
- q̂_a = η(t) (no travel recovery, no pending event processing)
- eta_sig[after] = q̂_a (flat trace, no exponential recovery from η_post)
- stl_travel_recovery_delta = 0
- stl_eta_at_apply = eta_now
- effective_feedback_beta = feedback_beta (no eta-weighting of historical suppression)

This preserves the variant A (submitted B4) results exactly for seeds 125-154 and
for any run with `stl_forecast_correction=False`.

**Where**: `task_value.py` `counterfactual_value()`, `planner_task_estimation.py`
diagnostic block, `DeterrentSystem.py` historical suppression block.
