# Thesis Dispatch Runbook

The April thesis dispatch reframe should be run as a dispatch-policy comparison over the `proposed` workload, not as a return to the legacy mode split.

Critical warning:
Thesis `react` means `simulation_mode="proposed"` with `dispatch_policy="react"`. It does **not** mean legacy `mode: "reactive"`, because legacy reactive mode disables predictive generation entirely and breaks the thesis funnel comparison.

For the visual demo configs in `configs/`, the planner baseline is held fixed at `planner_profile="thesis_calibrated_selective_proposed"`. The variant differences come from explicit dispatch kwargs:

- `dispatch_policy`
- `reservation_fraction`
- `reservation_window_s`
- `reactive_override_slack_s`
- `predictive_selection_policy`

This keeps the proposed workload and planner baseline constant while changing only the dispatch semantics.

## Official Variants

| Variant | Thesis Meaning | Planner Baseline | Dispatch Settings | Visual Demo Config | Batch / Testbench Command |
| --- | --- | --- | --- | --- | --- |
| `react` | Reactive-only admission over the proposed workload. Predictive tasks are still generated for funnel accounting but never admitted. | `thesis_calibrated_selective_proposed` | `dispatch_policy="react"` | `configs/demo_thesis_dispatch_core3.json` | `python -m testbench.run_testbench --config testbench/thesis_dispatch_policy_smoke.json --max-workers 1` |
| `unc` | Unconstrained baseline. Keeps the current production admission and ordering path. | `thesis_calibrated_selective_proposed` | `dispatch_policy="unc"` | `configs/demo_thesis_dispatch_core3.json` and `configs/demo_thesis_dispatch_random_ablation.json` | `python -m testbench.run_testbench --config testbench/thesis_dispatch_policy_smoke.json --max-workers 1` |
| `res_0p10` | Reserved-capacity dispatch with a light predictive-share target. | `thesis_calibrated_selective_proposed` | `dispatch_policy="res"`, `reservation_fraction=0.10` | `configs/demo_thesis_dispatch_reservation_sweep.json` | `python -m testbench.run_testbench --config testbench/thesis_reservation_sweep.json --max-workers 1` |
| `res_0p25` | Reserved-capacity dispatch with the nominal thesis target. | `thesis_calibrated_selective_proposed` | `dispatch_policy="res"`, `reservation_fraction=0.25`, utility predictive chooser | `configs/demo_thesis_dispatch_core3.json`, `configs/demo_thesis_dispatch_reservation_sweep.json`, `configs/demo_thesis_dispatch_random_ablation.json` | `python -m testbench.run_testbench --config testbench/thesis_dispatch_policy_smoke.json --max-workers 1` |
| `res_0p40` | Reserved-capacity dispatch with an aggressive predictive-share target. | `thesis_calibrated_selective_proposed` | `dispatch_policy="res"`, `reservation_fraction=0.40` | `configs/demo_thesis_dispatch_reservation_sweep.json` | `python -m testbench.run_testbench --config testbench/thesis_reservation_sweep.json --max-workers 1` |
| `res_rand_0p25` | Random-ablation version of the nominal reserved-capacity policy. Reservation logic stays fixed; predictive target choice becomes random. | `thesis_calibrated_selective_proposed` | `dispatch_policy="res"`, `reservation_fraction=0.25`, `predictive_selection_policy="random"` | `configs/demo_thesis_dispatch_random_ablation.json` | `python -m testbench.run_testbench --config testbench/thesis_random_ablation.json --max-workers 1` |
| `res_0p00` | Diagnostic-only edge case showing reserved-capacity logic with no predictive reservation. | Batch-only by default | `dispatch_policy="res"`, `reservation_fraction=0.0` | None by default | `python -m experiments.run_thesis_dispatch_policy_suite --include-rho0` |

## Core Comparison

The core thesis comparison is `react` vs `unc` vs `res_0p25`. This is the best first run if you want to see the reframe directly.

Visual demo config:
- `configs/demo_thesis_dispatch_core3.json`

Interactive demo:

```powershell
python -m demos.demo_systems --config configs/demo_thesis_dispatch_core3.json
```

Headless smoke run:

```powershell
python -m demos.demo_systems --config configs/demo_thesis_dispatch_core3.json --no-show --max-frames 5
```

Final-frame export:

```powershell
python -m demos.demo_systems --config configs/demo_thesis_dispatch_core3.json --save-figure results/demo_thesis_dispatch_core3.png
```

Batch comparison:

```powershell
python -m testbench.run_testbench --config testbench/thesis_dispatch_policy_smoke.json --max-workers 1
```

The smoke testbench is the authoritative batch comparison for the core three systems. It writes CSV, plots, and a markdown report under `results/testbench/thesis_dispatch_policy_smoke`.

## Reservation Sweep

The reservation sweep isolates the effect of `reservation_fraction` by comparing `res_0p10`, `res_0p25`, and `res_0p40`.

Visual demo config:
- `configs/demo_thesis_dispatch_reservation_sweep.json`

Interactive demo:

```powershell
python -m demos.demo_systems --config configs/demo_thesis_dispatch_reservation_sweep.json
```

Headless smoke run:

```powershell
python -m demos.demo_systems --config configs/demo_thesis_dispatch_reservation_sweep.json --no-show --max-frames 5
```

Final-frame export:

```powershell
python -m demos.demo_systems --config configs/demo_thesis_dispatch_reservation_sweep.json --save-figure results/demo_thesis_dispatch_reservation_sweep.png
```

Batch comparison:

```powershell
python -m testbench.run_testbench --config testbench/thesis_reservation_sweep.json --max-workers 1
```

Use the sweep when you want the thesis story about spare-capacity reservation rather than the high-level baseline comparison.

## Random Ablation

The random ablation compares `unc`, `res_0p25`, and `res_rand_0p25`. This isolates the predictive-selection rule while keeping the reserved-capacity logic fixed.

Visual demo config:
- `configs/demo_thesis_dispatch_random_ablation.json`

Interactive demo:

```powershell
python -m demos.demo_systems --config configs/demo_thesis_dispatch_random_ablation.json
```

Headless smoke run:

```powershell
python -m demos.demo_systems --config configs/demo_thesis_dispatch_random_ablation.json --no-show --max-frames 5
```

Final-frame export:

```powershell
python -m demos.demo_systems --config configs/demo_thesis_dispatch_random_ablation.json --save-figure results/demo_thesis_dispatch_random_ablation.png
```

Batch comparison:

```powershell
python -m testbench.run_testbench --config testbench/thesis_random_ablation.json --max-workers 1
```

## Diagnostic Rho 0

`res_0p00` is documented as a diagnostic-only variant. It is useful for confirming that the reserved-capacity implementation reduces to “no predictive reservation” when `rho = 0`, but it is not part of the default visual comparison bundle.

Primary entrypoint:

```powershell
python -m experiments.run_thesis_dispatch_policy_suite --include-rho0
```

Profile-plumbing smoke:

```powershell
python -m testbench.run_testbench --config testbench/thesis_profile_smoke.json --max-workers 1
```

## Batch Mode

The thesis batch configs already live under `testbench/`. They are the authoritative source for repeatable CSV/report artifacts.

Core policy smoke:

```powershell
python -m testbench.run_testbench --config testbench/thesis_dispatch_policy_smoke.json --max-workers 1
```

Reservation sweep:

```powershell
python -m testbench.run_testbench --config testbench/thesis_reservation_sweep.json --max-workers 1
```

Random ablation:

```powershell
python -m testbench.run_testbench --config testbench/thesis_random_ablation.json --max-workers 1
```

Funnel audit:

```powershell
python -m testbench.run_testbench --config testbench/thesis_funnel_audit.json --max-workers 1
```

Override stress:

```powershell
python -m testbench.run_testbench --config testbench/thesis_override_stress.json --max-workers 1
```

Profile smoke:

```powershell
python -m testbench.run_testbench --config testbench/thesis_profile_smoke.json --max-workers 1
```

Full thesis suite:

```powershell
python -m experiments.run_thesis_dispatch_policy_suite
```

Regression guardrail:

```powershell
python -m experiments.run_thesis_dispatch_regression_check
```


## Relationship To Habituation-Aware STL

The habituation-aware STL study is a value-function addendum, not a replacement for this dispatch-policy runbook. The dispatcher remains fixed and receives task fields through the existing `utility`/`score` contract.

Use this runbook for April dispatch policy comparisons (`react`, `unc`, `res_0p25`, reservation sweeps, and random ablations). Use `docs/HABITUATION_STL_CONFIRMATORY_RESULTS.md` and `docs/habituation_stl_completion_plan.md` for the proposal STL ladder (`B0` through `B4`).

Key distinction:

- dispatch runbook: changes `dispatch_policy`, `reservation_fraction`, and related admission semantics
- STL ladder: changes `predictive_utility_mode` and `stl_active_clauses` while preserving dispatch behavior
## Which Entrypoint To Use

- Use `python -m demos.demo_systems --config ...` when you want a live, synchronized visual comparison of exactly three thesis variants.
- Use `python -m testbench.run_testbench --config ...` when you want repeatable CSVs, time-series plots, a report, and a shared metric contract.
- Use `python -m experiments.run_thesis_dispatch_policy_suite` when you want the full thesis comparison table across the official variant set.
- Use `python -m experiments.run_thesis_dispatch_regression_check` after runtime changes when you want a short seeded guardrail that the dispatch reframe still behaves as expected.
