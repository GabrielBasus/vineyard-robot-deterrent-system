# Habituation STL Completion Record and Reproducibility Plan

This document records the implemented habituation-aware STL integration and the steps required to reproduce or extend the result. It replaces the earlier open integration plan.

## Target Claim

A habituation-aware spatio-temporal mission specification can make predictive multi-robot deterrence useful under habituating ground truth by selecting actions that reduce exposure, refresh coverage, and avoid overusing habituated cues.

## Implementation Status

Complete in the production path:

- `DeterrentSystem.py` creates and advances a `HabituationField`.
- Completed deterring actions update habituation and coverage-service state.
- Ground-truth suppression stores and applies `eta_at_apply`.
- Direct-detection deterrence is mapped to a physical cue bucket for habituation.
- `predictive_utility_mode="stl_robustness"` selects the STL counterfactual value path.
- `TaskGenerator.py` computes action variants and preserves STL utility fields for existing dispatchers.
- `planner_task_extraction.py` preserves STL values instead of recomputing legacy deltaJ.
- `planner_task_estimation.py` adapts SESTPP intensity, coverage age, and habituation state into `counterfactual_value(...)`.
- `system_structure.py` exports habituation and STL config/metric sections.
- Production ladder, diagnostic, and summarizer scripts exist under `experiments/`.
- Unit and package tests cover ground-truth habituation wiring and STL utility propagation.

## Baseline Ladder

| ID | Meaning | Production configuration |
| --- | --- | --- |
| B0 | Reactive-only reference | Predictive patrol/model-scored deterrence/fallback disabled. |
| B1 | Legacy unconstrained baseline | `dispatch_policy="unc"`, legacy predictive utility. |
| B2 | Prior SESTPP deltaJ value | Reserved dispatcher, `predictive_utility_mode="deltaJ"`. |
| B3 | STL without habituation clause | Reserved dispatcher, `predictive_utility_mode="stl_robustness"`, `stl_active_clauses=("exp","cov")`. |
| B4 | Full proposal | Reserved dispatcher, `predictive_utility_mode="stl_robustness"`, `stl_active_clauses=("exp","cov","hab")`. |

Each system should be run under both controls:

- habituation on: `enable_habituation=True`, `habituation_kappa > 0`
- habituation off: `enable_habituation=False` or `habituation_kappa=0.0`

## Reproduction Commands

Focused tests:

```powershell
C:\Users\gabri\AppData\Local\Programs\Python\Python310\python.exe -m py_compile DeterrentSystem.py planner_task_estimation.py experiments\diagnose_habituation_stl_production.py system_structure.py
$env:PYTHONPATH=(Resolve-Path .).Path; C:\Users\gabri\AppData\Local\Programs\Python\Python310\python.exe -m unittest tests.test_ground_truth_habituation_wiring
$env:PYTHONPATH=(Resolve-Path .).Path; C:\Users\gabri\AppData\Local\Programs\Python\Python310\python.exe -m unittest tests.test_predictive_utility_calibration.PredictiveUtilityPropagationTests.test_stl_robustness_overwrites_stale_legacy_utility
$env:PYTHONPATH=(Resolve-Path .\habituation_stl).Path; C:\Users\gabri\AppData\Local\Programs\Python\Python310\python.exe habituation_stl\tests\test_spec_value.py
```

B0-B4 900-second ladder:

```powershell
C:\Users\gabri\AppData\Local\Programs\Python\Python310\python.exe experiments\run_habituation_stl_production_ladder.py --outdir results\testbench\habituation_stl_b0_b4_900s_10seed_v5 --duration-s 900 --num-runs 10 --seed-start 125 --warmup-s 0 --nx 120 --ny 96 --nrobots 6 --max-workers 2
```

B1/B3/B4 1800-second confirmatory run:

```powershell
C:\Users\gabri\AppData\Local\Programs\Python\Python310\python.exe experiments\run_habituation_stl_production_ladder.py --outdir results\testbench\habituation_stl_confirm_b1_b3_b4_1800s_10seed_v5 --duration-s 1800 --num-runs 10 --seed-start 125 --warmup-s 0 --nx 120 --ny 96 --nrobots 6 --systems B1_unc_legacy B3_res_stl_nohab B4_res_stl_full --max-workers 2
```

Summarize a run directory:

```powershell
C:\Users\gabri\AppData\Local\Programs\Python\Python310\python.exe experiments\summarize_habituation_stl_ladder.py --outdir results\testbench\habituation_stl_confirm_b1_b3_b4_1800s_10seed_v5
```

## Current Evidence

The strongest current result is documented in `docs/HABITUATION_STL_CONFIRMATORY_RESULTS.md`.

Under habituating truth:

- B4 vs B1 exposure delta: `-2298.52`, 95% CI `[-4184.21, -412.82]`, 8/10 seeds improved.
- B4 vs B3 exposure delta: `-3288.10`, 95% CI `[-4112.47, -2463.73]`, 10/10 seeds improved.

Under non-habituating truth:

- B4 vs B3 exposure delta: `0.00`, 95% CI `[0.00, 0.00]`.

Mechanism under habituating truth:

- B4 increases `eta_at_apply` relative to B3.
- B4 increases cue variety relative to B3.
- B4 increases truth suppression rate relative to B3.

## Thesis-Ready Acceptance State

Accepted for thesis writing:

- production integration is complete
- ground-truth habituation is live and tested
- B3/B4 control semantics are correct
- confirmatory production result supports the central simulation claim
- reproducible commands and output locations are documented

Remaining before final thesis submission:

- decide whether to run a longer 24-hour version for robustness
- decide whether to run load/reservation sensitivity sweeps
- keep the biological interpretation conservative
- align final plots with the rest of the thesis figure style

## Primary Files

Implementation:

- `DeterrentSystem.py`
- `TaskGenerator.py`
- `planner_task_estimation.py`
- `planner_task_extraction.py`
- `system_structure.py`
- `habituation_stl/`

Validation:

- `tests/test_ground_truth_habituation_wiring.py`
- `tests/test_predictive_utility_calibration.py`
- `tests/test_task_generator_counterfactual_scoring.py`
- `habituation_stl/tests/test_spec_value.py`

Experiment scripts:

- `experiments/diagnose_habituation_stl_production.py`
- `experiments/run_habituation_stl_production_ladder.py`
- `experiments/summarize_habituation_stl_ladder.py`