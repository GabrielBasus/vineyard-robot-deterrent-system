# Habituation STL Completion Plan

This document tracks the remaining work to fully finish the habituation-aware STL integration and obtain thesis-grade results. It is based on `docs/proposal_stl.pdf` and the current production integration in `DeterrentSystem.py`, `TaskGenerator.py`, `planner_task_estimation.py`, `planner_task_extraction.py`, and `system_structure.py`.

## Target Claim

The thesis claim is that a habituation-aware spatio-temporal mission specification and counterfactual STL robustness predictive value can make predictive multi-robot deterrence valuable under realistic habituation, especially near saturated load, while retaining the existing SESTPP, zone partitioning, fleet model, and dispatcher logic.

## Proposal Requirements

The proposal defines four core implementation requirements:

1. Add explicit per-cell, per-cue habituation to the ground-truth suppression process.
2. Define predictive task value as counterfactual STL robustness `U(a,r)`.
3. Keep reserved-capacity dispatch logic unchanged; only predictive utility changes.
4. Evaluate a B0-B4 baseline ladder under habituating and non-habituating truth.

The required baseline ladder is:

| ID | Meaning | Production configuration |
| --- | --- | --- |
| B0 | Reactive-only lower reference | Disable predictive patrol/model-scored deterrence/fallback/intervention feedback |
| B1 | Greedy unconstrained prior baseline | `dispatch_policy="unc"`, `predictive_utility_mode="legacy"` |
| B2 | Prior SESTPP deltaJ value | Shared reserved dispatcher, `predictive_utility_mode="deltaJ"` |
| B3 | STL robustness without habituation clause | Shared reserved dispatcher, `predictive_utility_mode="stl_robustness"`, `stl_active_clauses=("exp","cov")` |
| B4 | Full proposal | Shared reserved dispatcher, `predictive_utility_mode="stl_robustness"`, `stl_active_clauses=("exp","cov","hab")` |

Every condition must be run with:

- Habituation ON: `enable_habituation=True`, `habituation_kappa > 0`
- Habituation OFF control: `enable_habituation=False` or `habituation_kappa=0.0`

## Current Status

Completed:

- `HabituationField` is wired into production `DeterrentSystem.py`.
- Ground-truth suppression is scaled by event `eta`.
- Completed deterring actions update the habituation field and coverage service time.
- `predictive_utility_mode="stl_robustness"` is supported.
- `TaskGenerator.py` computes STL counterfactual value and preserves `utility`, `score`, `predicted_deltaJ`, and `deltaJ_per_cost` for dispatch compatibility.
- `planner_task_extraction.py` passes through and preserves STL utility fields.
- STL and habituation diagnostics are present in final production metrics.
- Reference `habituation_stl` tests and B0-B4 reference ladder pass.
- One production smoke run completed through the STL path.

Not yet complete:

- Clean production B0-B4 ladder has not been run across paired seeds.
- New STL/habituation metrics are not yet guaranteed in all testbench summary contracts.
- Production tuning has not found a B4 configuration that improves primary exposure metrics.
- H1-H4 have not been evaluated in the production simulator.
- Thesis-grade 24-hour paired-seed results do not yet exist.

## Immediate Experiment

Run a short clean production ladder before committing to 24-hour sweeps:

- Systems: B0, B1, B2, B3, B4
- Controls: habituation on/off
- Seeds: `123, 124, 125`
- Duration: `900s` initially, then `1800s` if the signal is ambiguous
- Grid: start with production grid `W=500`, `H=500`, `NX=120`, `NY=96`, `Nrobots=6`
- Shared proposed task-generation settings for B1-B4
- Shared reserved dispatcher settings for B2-B4

Required outputs:

- `per_run_metrics.csv`
- `summary_by_system.csv`
- `advantage_vs_reference.csv`
- raw JSON metrics per system and seed

Primary columns:

- `value_weighted_exposure`
- `mean_response_time_s`
- `reactive_completed_total`
- `predictive_completed_total`
- `predictive_generated_total`
- `predictive_completion_ratio`
- `truth_suppression_rate`
- `birds_deterred_pct`
- `habituation_eta_mean`
- `habituation_eta_min`
- `habituation_eta_at_apply_mean`
- `habituation_variety_index`
- `stl_robustness_global_mean`
- `stl_robustness_global_min`
- `stl_robustness_exp`
- `stl_robustness_cov`
- `stl_robustness_hab`

## Acceptance Criteria

The integration is thesis-ready only when:

1. B0-B4 production runs complete for habituation on/off controls.
2. B2-B4 use identical dispatcher settings, isolating the predictive value function.
3. B4 behavior is interpretable from STL clause metrics.
4. At least one near-saturated habituating condition supports H1/H2.
5. The habituation-off control supports H4.
6. Runtime is manageable enough to reproduce results.
7. Plots and tables are generated from production runs, not only the reference harness.

## H1-H4 Decision Rules

- H1: Under habituating truth near `rho_load ~= 1`, B4 should reduce `value_weighted_exposure` relative to B1.
- H2: B4 should improve over B3 on exposure and/or full STL robustness, showing `phi_hab` adds value.
- H3: B3 should improve over B2, showing smooth robustness improves over hand-tuned deltaJ.
- H4: Under non-habituating truth, B4 should be close to B1, showing the advantage is habituation-specific.

## Follow-Up Sweeps

If the immediate ladder does not support H1/H2, tune before long sweeps:

- `stl_active_clauses`: `("exp",)`, `("exp","hab")`, `("exp","cov")`, `("exp","cov","hab")`
- `stl_E_star`
- `stl_eta_min`
- `stl_horizon_s`
- `stl_T_cov_s`
- `habituation_kappa`
- `habituation_T_rec_s`
- `reservation_fraction`

Then run the headline factor grid:

- `rho_load in {0.5, 1.0, 1.5}`
- `habituation_kappa in {low, med, high}`
- `reservation_fraction in {0, 0.10, 0.25, 0.40}`
- habituation on/off control
- 24-hour duration
- seeds `{123,124,125,126,127}`

## Notes

- The reference harness is a mechanism smoke test. Thesis claims must use production simulator outputs.
- The one-seed 900s production smoke showed STL robustness improved, but exposure did not improve; this suggests clause/threshold tuning is required.
- Production STL scoring is materially slower than legacy scoring. Long sweeps should be run as batch jobs, not interactive checks.

## 2026-07-22 Short Production Ladder Checkpoint

Completed run:

- `results/testbench/habituation_stl_production_ladder_short`
- B0-B4
- habituation on/off
- seeds `{123,124,125}`
- `T_end=900s`
- production grid `NX=120`, `NY=96`, `Nrobots=6`
- `reservation_fraction=0.25` for B2-B4

Generated artifacts:

- `per_run_metrics.csv`
- `summary_by_system.csv`
- `advantage_vs_reference.csv`
- raw JSON per system/seed

Main result:

| Baseline | Hab | Mean Jexp | Mean predictive completed | Mean eta at apply | Mean STL global |
| --- | --- | ---: | ---: | ---: | ---: |
| B0 reactive | off | 1340.219 | 0.000 | 1.000 | -0.536 |
| B0 reactive | on | 1340.219 | 0.000 | 0.962 | -0.536 |
| B1 unc legacy | off | 1323.857 | 21.667 | 1.000 | -0.196 |
| B1 unc legacy | on | 1323.857 | 21.667 | 0.589 | -0.196 |
| B2 res deltaJ | off | 1331.306 | 22.667 | 1.000 | -0.140 |
| B2 res deltaJ | on | 1331.306 | 22.667 | 0.821 | -0.140 |
| B3 res STL no-hab | off | 1316.915 | 23.333 | 1.000 | -0.170 |
| B3 res STL no-hab | on | 1316.915 | 23.333 | 0.728 | -0.170 |
| B4 res STL full | off | 1316.915 | 23.333 | 1.000 | -0.170 |
| B4 res STL full | on | 1316.915 | 23.333 | 0.728 | -0.170 |

Interpretation:

- The clean production ladder runs and exports the expected metrics.
- B3/B4 currently choose behavior indistinguishable from each other in this short configuration.
- Habituation state is changing (`eta_at_apply` drops under habituation on), but the primary exposure and suppression metrics are unchanged between habituation-on and habituation-off controls.
- Therefore the immediate blocker is not experiment execution; it is making production habituation materially affect the truth process and/or making the STL value change selected actions.

Next debugging/tuning steps before long sweeps:

1. Verify completed predictive model-scored deterring actions are actually inserted into the truth suppression history used by `lambda_true`.
2. Inspect a small run's completed deterring events for `(cell_id, mode, eta)` and confirm low-eta actions reduce suppression less than high-eta actions.
3. Run a concentrated/high-load short scenario where truth suppression is nonzero in most seeds.
4. Compare B3/B4 task rows directly (`predictive_stl_U`, selected mode, variants) to confirm whether `phi_hab` changes utility but is being neutralized by reservation/admission, or whether utility itself is too flat.
5. Only after those checks, run clause/threshold tuning sweeps.

## 2026-07-22 Diagnostic Runner Checkpoint

Added `experiments/diagnose_habituation_stl_production.py` to inspect where B3/B4 and habituation-on/off differences disappear before launching more long production runs.

Outputs:
- `diagnostic_final_metrics.csv`: final metrics for each baseline/habituation condition.
- `diagnostic_stage_rows.csv`: per-planning-stage candidate and accepted-task STL/habituation summaries.
- `diagnostic_deterrence_events.csv`: completed deterrence events from runtime tracking, including `eta`, mode, source, and suppression parameters.
- `diagnostic_b3_b4_stage_compare.csv`: paired B3-vs-B4 stage deltas for candidate/accepted counts and STL utility.
- `diagnostic_raw.json`: full compact diagnostic payload.

Validation command completed:

```powershell
C:\Users\gabri\AppData\Local\Programs\Python\Python310\python.exe experiments\diagnose_habituation_stl_production.py --outdir results\diagnostics\habituation_stl_production_debug_validation --duration-s 60 --seed 125 --warmup-s 0 --nx 30 --ny 24 --nrobots 3
```

Validation result: script ran and wrote all files, but a 60 s small-grid run did not create predictive deterring candidates or deterrence completion events. The next run should use the production short-run geometry/duration for one seed so the diagnostic captures candidate ranking, accepted deterring tasks, and event-level `eta` values.

## 2026-07-23 Ground-Truth Habituation Wiring Checkpoint

Verified and tightened the ground-truth habituation path:

- `hab.recover(dt)` runs during each ground-truth generation step.
- Completed deterring tasks query `hab.effectiveness(cell, mode)` before applying habituation, then call `hab.apply(cell, mode)`.
- Completed deterrence events are appended to `recent_deterrences` with `eta`.
- `_suppression_eval(...)` multiplies each event's truth suppression contribution by that `eta`.
- `last_service_t_by_cell` and `eta_at_apply_samples` are updated on completion for STL and metrics.

Fix applied: mode identity is now resolved independently from `use_mode_dependent_truth_suppression`. If shared truth suppression parameters are selected, predictive actions still habituate their actual cue mode instead of being collapsed into `direct_detection`.

Verification:

```powershell
C:\Users\gabri\AppData\Local\Programs\Python\Python310\python.exe -m unittest tests.test_ground_truth_habituation_wiring
```

Result: 3 tests passed. The live ground-truth probe confirms habituation-off deterrence events keep `eta=1.0`, while habituation-on repeated deterrence events produce `eta<1.0` and finite truth suppression metrics.

## 2026-07-23 Flat Jexp Diagnosis

The `results/diagnostics/habituation_stl_production_debug_seed125` files show that habituation state is changing, but realized `Jexp` remains identical because no truth candidates were actually suppressed in that production seed:

- B3/B4 `hab_on` deterrence events have lower event-level `eta` values after repeated laser use.
- B3/B4 `hab_off` deterrence events keep `eta=1.0`.
- Both `hab_on` and `hab_off` report `truth_suppression_rate=0.0` and `birds_deterred_pct=0.0` for seed 125.
- Therefore realized `value_weighted_exposure` cannot diverge in that seed; there are no accepted/suppressed truth outcomes for habituation to change.

A short high-load ground-truth probe verified the mechanism does change realized exposure when enough suppression opportunities exist:

- habituation off: `Jexp=1075.895`, `truth_suppressed_events=27`, `truth_suppression_effect_sum=33.232`, `eta_at_apply=1.0`.
- habituation on: `Jexp=1135.725`, `truth_suppressed_events=25`, `truth_suppression_effect_sum=20.641`, `eta_at_apply=0.538`.

Export fix applied: the production ladder and diagnostic scripts now include `truth_candidate_events`, `truth_accepted_events`, `truth_suppressed_events`, `truth_suppression_effect_mean`, and `truth_suppression_effect_sum`, so future runs can distinguish zero realized suppression from a wiring failure.

Next experiment step: rerun the production diagnostic or ladder with the added suppression-effect fields. If production still has near-zero suppression mass, the thesis experiment needs either longer horizons/more seeds or a calibrated high-load/suppression-sensitive condition; otherwise `Jexp` is statistically underpowered for habituation.

## 2026-07-23 Sensitivity Smoke Checkpoint

Added sensitivity knobs to the diagnostic and ladder runners:

- `--mu-true`
- `--alpha-true`
- `--beta-true`, `--sigma-true`, `--omega-true`
- `--deterrence-beta-scale`, `--deterrence-sigma-scale`, `--deterrence-omega-scale`

Defaults preserve the original production behavior. Non-default values create calibrated sensitivity runs for testing whether habituation is measurable under sufficient suppression opportunity.

Added `habituation_on_vs_off.csv` to ladder and summarizer outputs. This file reports paired seed deltas between `hab_on` and `hab_off` for each metric.

Smoke command completed:

```powershell
C:\Users\gabri\AppData\Local\Programs\Python\Python310\python.exe experiments\run_habituation_stl_production_ladder.py --outdir results\testbench\habituation_stl_sensitivity_b4_smoke --duration-s 420 --num-runs 2 --seed-start 125 --warmup-s 0 --nx 60 --ny 48 --nrobots 4 --systems B4_res_stl_full --max-workers 2 --mu-true 0.00002 --deterrence-beta-scale 4 --deterrence-sigma-scale 4 --deterrence-omega-scale 3
```

Key paired results (`hab_on - hab_off`, n=2):

- `truth_suppression_effect_sum`: `-4.100` expected events.
- `truth_suppressed_events`: `-2.0` realized events.
- `habituation_eta_at_apply_mean`: `-0.175`.
- `stl_robustness_hab`: `-0.790`.
- `value_weighted_exposure`: `-17.475`, but the two seeds disagree in direction, so `Jexp` is still noisy at n=2.

Interpretation: the sensitivity condition produces nonzero suppression mass and shows habituation reducing expected suppression, but a larger paired-seed run is needed before using realized `Jexp` as a thesis result.
