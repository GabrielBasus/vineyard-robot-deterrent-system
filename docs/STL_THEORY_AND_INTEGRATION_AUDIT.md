# STL Theory and Integration Audit

This note records how Signal Temporal Logic (STL) is used in the habituation
integration, how that maps to `docs/proposal_stl.pdf`, and what still needs to
be verified before using the results as thesis evidence.

## Purpose

The proposal reframes predictive bird deterrence as a spatio-temporal
specification satisfaction problem. The key change is:

```text
Predictive task value = counterfactual STL robustness improvement
```

Instead of ranking predictive tasks by a hand-tuned scalar exposure reduction,
the planner scores a candidate action `a` for robot `r` as:

```text
U(a, r) = robustness(Phi_r, xi_with_action) - robustness(Phi_r, xi_without_action)
```

This is implemented as `counterfactual_value(...)` in
`habituation_stl/task_value.py` and is passed through the existing task
generator/dispatcher as `predictive_stl_U`, `utility`, and `score`.

## STL Background

STL formulas are evaluated over real-valued time signals. In this project, the
signals are sampled at a fixed monitor period:

- `e_z(t)`: value-weighted exposure or exposure rate for cell `z`
- `g_z(t)`: coverage age for cell `z`
- `eta_z(t)`: effectiveness of the deterrence cue active in cell `z`
- optionally `arr_a(t)` and `srv_a(t)` for reactive task deadlines

The quantitative STL semantics returns a real robustness value:

- positive robustness means the formula is satisfied with margin
- zero means the formula is exactly on the boundary
- negative means the formula is violated

Classical STL conjunction uses `min`. This project also implements a smooth
soft-min aggregator so non-binding clauses still influence the score.

Implementation:

- `habituation_stl/stl.py`
  - `Pred`, `Neg`, `And`, `Or`, `Implies`
  - `Always`, `Eventually`, `Until`
  - past-time operators `Once`, `Historically`, `Since`
  - `Aggregator("smooth", theta)` for soft-min/soft-max robustness
  - `Scale` for clause weighting

## Mission Specification

The proposal defines a mission formula:

```text
Phi = phi_exp AND phi_react AND phi_cov AND phi_hab
```

The current production integration uses the following clauses:

| Clause | Meaning | Implementation |
|---|---|---|
| `phi_exp` | keep exposure below budget `E_star` | `e_z <= E_star` |
| `phi_cov` | keep coverage age below `T_cov` | `g_z <= T_cov` |
| `phi_hab` | active deterrence should use an effective cue | `eta_z >= eta_min` |
| `phi_react` | reactive arrivals should be serviced before deadline | present in `mission_spec.py`, not currently central in production predictive scoring |

Implementation:

- `habituation_stl/mission_spec.py`
  - `SpecParams`
  - `build_clauses(...)`
  - `build_spec(...)`
  - `build_inner_clauses(...)`

Important details:

- Predicate margins are normalized by thresholds, matching the proposal's
  scale-comparability requirement.
- `active_clauses` controls whether B3 uses `("exp", "cov")` and B4 uses
  `("exp", "cov", "hab")`.
- `clause_weights` are now applied through `Scale(...)`.
- The returned per-clause dictionary remains unweighted for diagnostics.

## Habituation Model

The proposal uses per-cell, per-cue effectiveness:

```text
eta[z, mode] in (0, 1]
```

Effectiveness recovers toward `1.0` over time and drops after a cue is applied.

Implementation:

- `habituation_stl/habituation.py`
  - `HabituationField.recover(dt)`
  - `HabituationField.apply(cell, mode)`
  - `HabituationField.effectiveness(cell, mode)`

Production wiring:

- `DeterrentSystem.py` creates one `HabituationField`.
- Every truth step recovers the field.
- Every completed deterrence action applies a mode-specific habituation update.
- Ground-truth suppression is scaled by `eta_at_apply`.
- `direct_detection_habituation_mode="laser"` maps reactive direct detections
  onto a physical cue bucket instead of a separate non-physical mode.

The direct-detection mapping is important. Without it, reactive completions
would degrade only a `direct_detection` bucket, while B4 candidate scoring
evaluates `formation`, `laser`, and `biosonic`; B4 would then see all predictive
cues as fresh.

## Counterfactual Task Value

The proposal's Algorithm 2 is implemented by
`habituation_stl/task_value.py::counterfactual_value(...)`.

For a candidate action `(target_cell, mode, completion_lead_s)`:

1. Build the nominal trajectory `xi_without_action`.
2. Copy it to `xi_with_action`.
3. From the completion lead onward:
   - reduce `e_target` by an effectiveness-scaled suppression bump
   - reset `g_target`
   - set `eta_target` to the cue effectiveness at application
4. Evaluate the local STL spec on both traces.
5. Return the robustness difference.

Production adapters live in `planner_task_estimation.py`:

- derive local cells for the robot
- compute exposure from the robot's SESTPP intensity field
- compute coverage age from `last_service_t_by_cell`
- map mode labels to habituation/STL mode ids
- return `predictive_stl_U` plus diagnostic fields such as
  `stl_eta_at_apply`

## B3 vs B4 Semantics

The proposal's ladder isolates the value-function components:

- B3: STL robustness without the habituation clause
- B4: STL robustness with the habituation clause

The implementation now follows that separation:

- B3 uses `stl_active_clauses=("exp", "cov")`
- B4 uses `stl_active_clauses=("exp", "cov", "hab")`
- when `"hab"` is not active, the planner-side counterfactual assumes
  `eta_app = 1.0`
- when `"hab"` is active, `eta_app = hab.effectiveness(cell, mode)`

This matters because B3 should isolate the robustness reformulation itself,
while B4 should add habituation-aware mode selection. The ground truth may still
have habituation on or off independently, as required by the proposal's control
design.

## Dispatcher Consistency

The proposal explicitly says the dispatcher should remain unchanged and only the
predictive value should be replaced.

That is how the current integration works:

- `TaskGenerator.py` computes `predictive_stl_U`.
- STL mode sets compatibility fields:
  - `utility`
  - `score`
  - `predicted_deltaJ`
  - `deltaJ_per_cost`
- `planner_task_extraction.py` now forces `utility` and `score` from
  `predictive_stl_U` in STL mode.
- existing dispatch policies still rank by their normal task fields.

No command runners or experiment command files are required for this behavior.

## Online Monitoring

The proposal's Algorithm 1 is represented by `habituation_stl/signals.py`.

`RobotMonitor` keeps rolling buffers for each robot's local cells and reports:

- per-clause robustness
- global smooth-min robustness

Production exports include:

- `stl_robustness_global_mean`
- `stl_robustness_global_min`
- `stl_robustness_exp`
- `stl_robustness_cov`
- `stl_robustness_hab`
- `habituation_eta_mean`
- `habituation_eta_min`
- `habituation_eta_at_apply_mean`
- `habituation_variety_index`

The monitor is currently diagnostic/telemetry. Predictive task value uses the
forward-looking counterfactual in `task_value.py`.

## Current Consistency Assessment

The integration is now broadly consistent with the proposal:

- STL robustness is used as the predictive task value.
- B3 and B4 are separated by `active_clauses`.
- B4 sees reduced cue effectiveness when the physical cue has been repeated.
- Direct detections now habituate a physical cue bucket.
- Dispatcher logic remains unchanged.
- Ground truth uses habituation-scaled suppression.
- Diagnostics expose candidate-level STL utility and cue effectiveness.

Recent diagnostic result:

- `B4_res_stl_full/hab_on` laser candidates now show reduced
  `stl_eta_at_apply`.
- B3 remains fresh in candidate scoring.
- B4 candidate mode preference shifted from laser toward formation in the short
  single-seed probe.
- Accepted tasks did not yet diverge in the 420-second single-seed diagnostic,
  so longer/multi-seed evidence is still needed.

## Known Deviations and Risks

1. `phi_react` is implemented but not currently the main differentiator in the
   predictive counterfactual path. Reactive protection still comes from the
   existing dispatcher and override logic.

2. The proposal describes a past-time cue-variety form and a continuous
   effectiveness-floor form. The implementation uses the effectiveness-floor
   form for scoring and an entropy-style variety metric for reporting.

3. The online monitor uses non-temporal inner clauses over a trailing buffer,
   then takes the historical minimum. This is consistent with run-so-far
   telemetry, but task value uses the forward-looking STL formula.

4. The suppression predictor is a cheap analytic approximation. It uses local
   cell exposure and a self-cell suppression bump rather than a full spatial
   rollout of the SESTPP field.

5. B4's effect may still be too weak to change accepted tasks or exposure under
   short runs. If long runs still show weak separation, tune:
   - `stl_eta_min`
   - `clause_weights["hab"]`
   - habituation strength `kappa`
   - direct-detection physical cue mapping
   - scenario load and hotspot concentration

## Verification Checklist

Before thesis-scale results, verify:

- `diagnostic_action_variants.csv` shows B3 and B4 differ only when
  habituation is on.
- B4's habituated cue has lower `stl_eta_at_apply`.
- B4 candidate utilities penalize the habituated cue.
- B4 selected candidate modes show more variety than B3.
- accepted predictive tasks eventually diverge in longer runs.
- exposure or robustness improves statistically across paired seeds.

## Files to Revisit

- `docs/proposal_stl.pdf`
- `habituation_stl/stl.py`
- `habituation_stl/mission_spec.py`
- `habituation_stl/task_value.py`
- `habituation_stl/signals.py`
- `habituation_stl/habituation.py`
- `planner_task_estimation.py`
- `planner_task_extraction.py`
- `TaskGenerator.py`
- `DeterrentSystem.py`
- `experiments/diagnose_habituation_stl_production.py`
- `experiments/run_habituation_stl_production_ladder.py`
