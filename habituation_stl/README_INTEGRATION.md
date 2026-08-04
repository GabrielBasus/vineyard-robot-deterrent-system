# habituation_stl Integration Guide

`habituation_stl` contains the reusable STL and habituation implementation used by the production vineyard simulator. It is intentionally small and `numpy`-only so the production system can keep its existing SESTPP model, zone partitioning, robot fleet logic, task admission, and dispatch policies.

The package replaces the predictive deterrence value when the simulator is configured with:

```text
predictive_utility_mode = "stl_robustness"
```

## Module Map

| Module | Responsibility |
| --- | --- |
| `stl.py` | Quantitative STL robustness operators, temporal operators, smooth aggregators, and clause scaling. |
| `habituation.py` | `HabituationField`, a per-cell/per-mode cue-effectiveness model with recovery and application updates. |
| `mission_spec.py` | `SpecParams` and mission clauses for exposure, coverage, habituation, and reactive timing. |
| `task_value.py` | Counterfactual task value `U(a,r)` from robustness improvement. |
| `signals.py` | `RobotMonitor` for rolling STL robustness telemetry. |
| `metrics.py` | Utility metrics for exposure, cue variety, and habituation diagnostics. |
| `dispatch.py` | Reference reserved-capacity dispatcher used by the standalone harness. |
| `reference_sim.py`, `experiment.py` | Standalone smoke-test simulation and B0-B4 reference ladder. |

## Production Integration

Production adapters live outside this package:

- `DeterrentSystem.py` owns runtime habituation state, ground-truth suppression scaling, coverage service time, and final metrics.
- `planner_task_estimation.py` converts SESTPP fields and coverage memory into `CellState` inputs for `counterfactual_value(...)`.
- `TaskGenerator.py` scores model-scored predictive deterrence candidates and selects the best action mode.
- `planner_task_extraction.py` preserves STL utility fields for dispatch.
- `system_structure.py` exports STL and habituation config/metric sections.

The dispatchers do not need special STL logic. STL mode writes `predictive_stl_U` and mirrors it into `utility`, `score`, `predicted_deltaJ`, and `deltaJ_per_cost`.

## Ground-Truth Habituation

The truth path uses the same `HabituationField` concept as the planner value.

Per completed deterrence event:

1. resolve the cell and physical cue mode
2. read current `eta_at_apply`
3. append the deterrence event with that `eta`
4. apply habituation to the field
5. update coverage service time for the cell

During truth-event filtering, suppression from a recent deterrence event is multiplied by its stored `eta`:

```text
suppression = eta_at_apply * beta_mode * spatial_kernel * temporal_decay
```

This makes repeated cue use less effective in the simulated world.

## STL Task Value

For candidate action `a` and robot `r`, the production planner computes:

```text
U(a,r) = robustness(Phi_r, trace_with_action) - robustness(Phi_r, trace_without_action)
```

The trace contains local-cell exposure, coverage age, and cue effectiveness. B3 and B4 differ only in the active clause set:

- B3: `("exp", "cov")`
- B4: `("exp", "cov", "hab")`

When the habituation clause is inactive, planner-side `eta_app` is treated as `1.0`. When the clause is active, `eta_app` is read from the live habituation field.

## Tests

Run package-level tests from the repo root:

```powershell
$env:PYTHONPATH=(Resolve-Path .\habituation_stl).Path
C:\Users\gabri\AppData\Local\Programs\Python\Python310\python.exe habituation_stl\tests\test_spec_value.py
```

Run production wiring tests:

```powershell
$env:PYTHONPATH=(Resolve-Path .).Path
C:\Users\gabri\AppData\Local\Programs\Python\Python310\python.exe -m unittest tests.test_ground_truth_habituation_wiring
C:\Users\gabri\AppData\Local\Programs\Python\Python310\python.exe -m unittest tests.test_predictive_utility_calibration.PredictiveUtilityPropagationTests.test_stl_robustness_overwrites_stale_legacy_utility
```

## Production Experiments

B0-B4 ladder:

```powershell
C:\Users\gabri\AppData\Local\Programs\Python\Python310\python.exe experiments\run_habituation_stl_production_ladder.py --outdir results\testbench\habituation_stl_b0_b4_900s_10seed_v5 --duration-s 900 --num-runs 10 --seed-start 125 --warmup-s 0 --nx 120 --ny 96 --nrobots 6 --max-workers 2
```

Confirmatory B1/B3/B4 batch:

```powershell
C:\Users\gabri\AppData\Local\Programs\Python\Python310\python.exe experiments\run_habituation_stl_production_ladder.py --outdir results\testbench\habituation_stl_confirm_b1_b3_b4_1800s_10seed_v5 --duration-s 1800 --num-runs 10 --seed-start 125 --warmup-s 0 --nx 120 --ny 96 --nrobots 6 --systems B1_unc_legacy B3_res_stl_nohab B4_res_stl_full --max-workers 2
```

Summarize results:

```powershell
C:\Users\gabri\AppData\Local\Programs\Python\Python310\python.exe experiments\summarize_habituation_stl_ladder.py --outdir results\testbench\habituation_stl_confirm_b1_b3_b4_1800s_10seed_v5
```

## Documentation

- `docs/STL_THEORY_AND_INTEGRATION_AUDIT.md`
- `docs/HABITUATION_STL_CONFIRMATORY_RESULTS.md`
- `docs/habituation_stl_completion_plan.md`
- `docs/proposal_stl.pdf`