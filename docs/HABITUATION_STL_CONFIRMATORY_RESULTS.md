# Habituation-Aware STL Confirmatory Results

This document summarizes the current thesis-facing production evidence for the habituation-aware STL integration.

Primary run:

```text
results/testbench/habituation_stl_confirm_b1_b3_b4_1800s_10seed_v5
```

The batch compares three production systems with identical paired seeds and both habituating and non-habituating truth controls:

| System | Meaning |
| --- | --- |
| `B1_unc_legacy` | Legacy unconstrained predictive dispatcher using the legacy value path. |
| `B3_res_stl_nohab` | Reserved-capacity STL robustness value using exposure and coverage clauses only. |
| `B4_res_stl_full` | Reserved-capacity STL robustness value using exposure, coverage, and habituation clauses. |

Run shape:

- duration: 1800 seconds
- seeds: 125-134
- habituation controls: on and off
- completed jobs: 60
- production simulator: `DeterrentSystem.py`
- runner: `experiments/run_habituation_stl_production_ladder.py`

## Primary Exposure Result

Under habituating ground truth, B4 reduced value-weighted exposure relative to both references.

| Comparison | Mean paired delta in Jexp | 95% CI | Seeds improved |
| --- | ---: | ---: | ---: |
| B4 - B1 | -2298.52 | [-4184.21, -412.82] | 8/10 |
| B4 - B3 | -3288.10 | [-4112.47, -2463.73] | 10/10 |

Negative deltas are better because lower value-weighted exposure is the desired outcome.

Interpretation: the full habituation-aware STL value function improved the primary mission metric in the calibrated habituating condition.

## Falsifiable Control

With habituation disabled, B4 and B3 are exactly matched on exposure and task metrics.

| Comparison | Mean paired delta in Jexp | 95% CI |
| --- | ---: | ---: |
| B4 - B3, habituation off | 0.00 | [0.00, 0.00] |

This is the expected control result. It shows that B4's advantage is not caused by an unrelated dispatch-path difference. The difference appears when the ground truth includes habituation and disappears when habituation is disabled.

## Mechanism Evidence

Against B3 under habituating truth, B4 improved the metrics that the habituation clause is designed to influence.

| Metric | Mean paired delta B4 - B3 | 95% CI |
| --- | ---: | ---: |
| Truth suppression rate | +0.0630 | [+0.0467, +0.0793] |
| Eta at apply | +0.1454 | [+0.0843, +0.2064] |
| Variety index | +0.3072 | [+0.2390, +0.3755] |

Mechanism interpretation:

1. B4 penalizes repeatedly used cues through the STL `hab` clause.
2. Candidate selection shifts toward fresher modes.
3. Action-time effectiveness is higher.
4. Higher effectiveness increases truth suppression.
5. Increased suppression lowers value-weighted exposure.

## Thesis Claims

Supported by the current production results:

- The production system has live ground-truth habituation: repeated cue use lowers `eta_at_apply`, and truth suppression is scaled by that value.
- STL robustness can be used as a drop-in predictive task value while keeping dispatch policies unchanged.
- The habituation clause adds value under habituating truth: B4 beats B3 with a paired CI below zero.
- The effect is habituation-specific: B4 collapses to B3 when habituation is disabled.
- B4 beats the legacy practical baseline B1 in the current 1800-second confirmatory batch.

Not fully established by this batch alone:

- biological realism of the habituation law
- 24-hour production-scale stability
- broad sensitivity across all load, robot-count, and reservation-fraction settings

## Generated Artifacts

Primary summary files:

- `results/testbench/habituation_stl_confirm_b1_b3_b4_1800s_10seed_v5/THESIS_RESULTS_SUMMARY.md`
- `results/testbench/habituation_stl_confirm_b1_b3_b4_1800s_10seed_v5/ladder_manifest.json`

Advisor figures:

- `results/testbench/habituation_stl_confirm_b1_b3_b4_1800s_10seed_v5/advisor_figures/exposure_mean_ci_by_system.png`
- `results/testbench/habituation_stl_confirm_b1_b3_b4_1800s_10seed_v5/advisor_figures/hab_on_exposure_per_seed.png`
- `results/testbench/habituation_stl_confirm_b1_b3_b4_1800s_10seed_v5/advisor_figures/hab_on_b4_paired_exposure_deltas.png`
- `results/testbench/habituation_stl_confirm_b1_b3_b4_1800s_10seed_v5/advisor_figures/hab_on_b4_b3_mechanism_deltas.png`

Related pilot and diagnostic outputs:

- `results/testbench/habituation_stl_b0_b4_900s_10seed_v5`
- `results/testbench/habituation_stl_b3_b4_900s_10seed_v5`
- `results/diagnostics/`

## Recommended Thesis Framing

Use the result as simulation evidence for this claim:

> In a production multi-robot vineyard simulator with habituating deterrence effectiveness, replacing legacy predictive deterrence value with a habituation-aware STL robustness improvement reduces value-weighted exposure and increases cue variety. The no-habituation control collapses the full STL system to the no-habituation STL baseline, isolating the effect of the habituation clause.

Avoid overstating:

- Do not claim field validation.
- Do not claim the habituation parameters are biologically fitted.
- Do not treat global STL robustness as the sole result metric; B4 includes a stricter formula than B3, so exposure and mechanism metrics carry the primary comparison.