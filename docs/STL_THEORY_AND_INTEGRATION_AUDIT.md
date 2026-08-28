# STL Theory and Production Integration Audit

This document records how Signal Temporal Logic (STL) and cue habituation are implemented in the production simulator. It supersedes the earlier planning notes and should be read together with `docs/proposal_stl.pdf` and `docs/HABITUATION_STL_CONFIRMATORY_RESULTS.md`.

## Integration Status

The habituation-aware STL integration is implemented in the production path.

Implemented:

- per-cell, per-cue habituation state in the production truth loop
- truth suppression scaled by action-time effectiveness `eta_at_apply`
- opt-in predictive value mode `predictive_utility_mode="stl_robustness"`
- counterfactual STL task value `U(a,r)` for model-scored predictive deterrence
- B3/B4 clause separation through `stl_active_clauses`
- existing dispatcher policies preserved through compatibility fields `utility`, `score`, `predicted_deltaJ`, and `deltaJ_per_cost`
- STL and habituation diagnostics exported in production metrics and task previews
- production ladder and confirmatory experiment runners

The integration keeps SESTPP, zone partitioning, robot fleet logic, task admission, and dispatch commands intact. The predictive value function is the intentionally changed component.

## STL Background

Signal Temporal Logic evaluates formulas over real-valued time signals and returns a quantitative robustness margin. Positive robustness means the signal satisfies the formula with margin. Negative robustness means it violates the formula.

The production integration uses sampled robot-local traces:

- `e_z(t)`: value-weighted exposure rate for cell `z`
- `g_z(t)`: coverage age for cell `z`
- `eta_z(t)`: effectiveness of the candidate deterrent cue in cell `z`

The package implementation is in `habituation_stl/stl.py` and includes predicates, Boolean operators, future temporal operators, past-time operators, smooth aggregators, and clause scaling.

## Mission Specification

The proposal mission is represented as a conjunction of clauses:

```text
Phi = phi_exp AND phi_cov AND phi_hab
```

A reactive-deadline clause is also implemented in `habituation_stl/mission_spec.py`, but the production predictive value currently focuses on exposure, coverage, and habituation because reactive protection remains handled by the existing direct-detection dispatcher priority.

Production clauses:

| Clause | Signal test | Purpose |
| --- | --- | --- |
| `exp` | `e_z <= stl_E_star` | reward predicted exposure reduction |
| `cov` | `g_z <= stl_T_cov_s` | reward serving stale cells |
| `hab` | `eta_z >= stl_eta_min` | penalize repeated use of habituated cues |

The active clause set controls the B0-B4 ladder:

- B3 uses `stl_active_clauses=("exp", "cov")`.
- B4 uses `stl_active_clauses=("exp", "cov", "hab")`.

This separation is important. B3 tests whether STL robustness itself is useful. B4 tests whether adding the habituation clause changes behavior and improves outcomes when ground truth habituates.

## Counterfactual Task Value

For each candidate predictive action `a` and robot `r`, the planner computes:

```text
U(a,r) = robustness(Phi_r, trace_with_action) - robustness(Phi_r, trace_without_action)
```

Implementation:

- `habituation_stl/task_value.py::counterfactual_value(...)`
- `planner_task_estimation.py::estimate_stl_counterfactual_value(...)`
- `TaskGenerator.py` candidate scoring when `predictive_utility_mode="stl_robustness"`

The adapter constructs a robot-local cell state from the SESTPP field and coverage memory:

- exposure rate from value-weighted `rob.m.lam`
- coverage age from `last_service_t_by_cell`
- cue effectiveness from `HabituationField.effectiveness(cell, mode)`
- completion lead from candidate ETA/service timing

The selected STL value is exported as `predictive_stl_U` and mirrored into legacy dispatch fields so the dispatcher does not need a special STL branch.

## Habituation Model

`habituation_stl/habituation.py` implements `HabituationField`, a per-cell, per-mode effectiveness state. Effectiveness recovers toward `1.0` over time and drops when a cue is applied.

Production wiring in `DeterrentSystem.py`:

- `hab.recover(dt)` runs during the truth step.
- completed deterring tasks read `eta_at_apply` before applying habituation.
- completed deterring tasks call `hab.apply(cell, mode)`.
- recent deterrence events store `eta`.
- `_suppression_eval(...)` multiplies truth suppression by stored `eta`.
- direct-detection deterring is mapped onto a physical cue bucket through `direct_detection_habituation_mode="laser"`.

The non-habituating control is produced by setting `enable_habituation=False` or `habituation_kappa=0.0`.

## Dispatcher Consistency

The proposal requires the dispatcher to remain unchanged. The production integration follows that requirement.

In STL mode, `TaskGenerator.py` sets:

- `predictive_stl_U = U`
- `utility = U`
- `score = U`
- `predicted_deltaJ = U`
- `deltaJ_per_cost = U / cost`

`planner_task_extraction.py` preserves these values. Existing dispatch policies such as `unc`, `res`, `res-soft`, `res-adaptive`, `time-aware`, and `risk-adjusted` continue to rank by the same fields they already used.

## Production Telemetry

Production metrics now include:

- `habituation_eta_mean`
- `habituation_eta_min`
- `habituation_eta_at_apply_mean`
- `habituation_variety_index`
- `stl_robustness_global_mean`
- `stl_robustness_global_min`
- `stl_robustness_exp`
- `stl_robustness_cov`
- `stl_robustness_hab`
- `truth_candidate_events`
- `truth_accepted_events`
- `truth_suppressed_events`
- `truth_suppression_effect_mean`
- `truth_suppression_effect_sum`

These fields are required for diagnosing whether a run has enough suppression opportunity for habituation to affect realized exposure.

## Validation Summary

Focused checks passed during integration:

```powershell
C:\Users\gabri\AppData\Local\Programs\Python\Python310\python.exe -m py_compile DeterrentSystem.py planner_task_estimation.py experiments\diagnose_habituation_stl_production.py system_structure.py
$env:PYTHONPATH=(Resolve-Path .).Path; C:\Users\gabri\AppData\Local\Programs\Python\Python310\python.exe -m unittest tests.test_ground_truth_habituation_wiring
$env:PYTHONPATH=(Resolve-Path .).Path; C:\Users\gabri\AppData\Local\Programs\Python\Python310\python.exe -m unittest tests.test_predictive_utility_calibration.PredictiveUtilityPropagationTests.test_stl_robustness_overwrites_stale_legacy_utility
$env:PYTHONPATH=(Resolve-Path .\habituation_stl).Path; C:\Users\gabri\AppData\Local\Programs\Python\Python310\python.exe habituation_stl\tests\test_spec_value.py
```

Production evidence is summarized in `docs/HABITUATION_STL_CONFIRMATORY_RESULTS.md`. The strongest current result is the 1800-second, 10-seed B1/B2/B3/B4 confirmatory batch:

- B4 improves over B1 under habituation: mean paired exposure delta `-3696.74`, 95% CI `[-5226.86, -2166.61]`.
- B4 improves over B3 under habituation: mean paired exposure delta `-4277.35`, 95% CI `[-5791.31, -2763.40]`.
- B3 improves over B2 directionally under habituation: mean paired exposure delta `-689.90`, 95% CI `[-1537.63, +157.84]`.
- B4 and B3 are identical when habituation is disabled: exposure delta `0.00`.

## Known Scope Limits

- The habituation model is a stylized simulation mechanism, not a fitted biological model.
- `phi_react` is implemented but not the primary production predictive-score differentiator.
- The counterfactual rollout is a local analytic approximation rather than a full future SESTPP simulation.
- The global STL robustness metric is stricter for B4 because B4 includes the habituation clause; exposure and mechanism metrics are the primary thesis evidence.

## Risks, Mitigations, and Threats to Validity

Risks and mitigations:

- Flat task values were the failure mode that motivated this revision. The integration mitigates that risk by replacing the hand-tuned scalar value with smooth STL robustness, AGM-style smooth aggregation, and per-clause normalization.
- Habituation could be too weak to be visible in realized exposure. The experiment mitigates this through a concentrated high-value stress scenario, an explicit `habituation_kappa` setting, and paired habituation-off controls that bound the effect size.
- Decentralized monitoring can miss cross-zone behavior at partition boundaries. The production simulator mitigates this through the existing `EventBus` boundary-event sharing path and robot-local STL monitors over each robot's local cells plus boundary-adjacent cells.
- Horizon and monitor-period sensitivity are acknowledged secondary parameters. The headline experiments fix `stl_horizon_s` and `stl_monitor_dt_s` at documented defaults rather than sweeping them.

Threats to validity:

- The study is simulation-only and does not include physical-robot validation.
- The simulator owns the ground-truth event process used for evaluation.
- Detection noise is not the primary modeled uncertainty in the headline STL ladder.
- The predictive workload generator is in-house.
- The habituation law is a stylized abstraction and is not fitted to ecological field data.

These limitations are framework-level limits on external validity. The supported claim is narrower: within the same production simulator, workload setting, SESTPP model, and dispatcher contract, changing the predictive value function to habituation-aware STL robustness improves performance under habituating truth. Claims about robustness across alternative workload generators, ecological parameterizations, or real deployments require additional validation.

## Files

Core package:

- `habituation_stl/stl.py`
- `habituation_stl/mission_spec.py`
- `habituation_stl/task_value.py`
- `habituation_stl/habituation.py`
- `habituation_stl/signals.py`
- `habituation_stl/metrics.py`

Production adapters:

- `DeterrentSystem.py`
- `TaskGenerator.py`
- `planner_task_estimation.py`
- `planner_task_extraction.py`
- `system_structure.py`

Experiment tools:

- `experiments/diagnose_habituation_stl_production.py`
- `experiments/run_habituation_stl_production_ladder.py`
- `experiments/summarize_habituation_stl_ladder.py`
