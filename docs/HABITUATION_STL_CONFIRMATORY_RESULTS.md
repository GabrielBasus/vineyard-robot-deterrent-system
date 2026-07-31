# Habituation-Aware STL Confirmatory Results

This draft summarizes the 1800-second confirmatory batch:

`results/testbench/habituation_stl_confirm_b1_b3_b4_1800s_10seed_v5`

The batch compares three production systems:

- `B1_unc_legacy`: legacy unconstrained predictive dispatcher.
- `B3_res_stl_nohab`: reserved-capacity STL robustness value without the habituation clause.
- `B4_res_stl_full`: full reserved-capacity habituation-aware STL value.

Each system was run with habituation enabled and disabled over seeds 125-134.
The run produced 60 completed jobs.

## Primary Result

Under habituating ground truth, B4 reduced value-weighted exposure relative to
both references:

| Comparison | Mean paired delta in Jexp | 95% CI | Seeds improved |
|---|---:|---:|---:|
| B4 - B1 | -2298.52 | [-4184.21, -412.82] | 8/10 |
| B4 - B3 | -3288.10 | [-4112.47, -2463.73] | 10/10 |

Negative deltas are better because they indicate lower value-weighted exposure.

This supports the central thesis claim: when deterrence effectiveness degrades
with repeated cues, the full habituation-aware STL value function makes
predictive work operationally useful.

## Falsifiable Control

With habituation disabled, B4 and B3 are exactly matched on exposure and task
metrics:

| Comparison | Mean paired delta in Jexp | 95% CI |
|---|---:|---:|
| B4 - B3, habituation off | 0.00 | [0.00, 0.00] |

This is the desired control. It shows that B4's advantage is not caused by an
unrelated dispatch-path difference; it appears only when the ground truth
contains habituation.

## Mechanism Evidence

Against B3 under habituating truth, B4 improves the mechanism metrics that the
STL habituation clause is designed to influence:

| Metric | Mean paired delta B4 - B3 | 95% CI |
|---|---:|---:|
| Truth suppression rate | +0.0630 | [+0.0467, +0.0793] |
| Eta at apply | +0.1454 | [+0.0843, +0.2064] |
| Variety index | +0.3072 | [+0.2390, +0.3755] |

The mechanism is therefore coherent: B4 increases cue variety and preserves
application-time cue effectiveness; this increases truth suppression; increased
suppression reduces value-weighted exposure.

## Interpretation

The B3/B4 contrast isolates the value of the habituation clause. B3 already uses
the STL robustness reformulation for exposure and coverage, but it does not
penalize repeated cue use. B4 adds `phi_hab`, causing candidate scoring to
discount habituated cues and prefer fresher modes when appropriate. In the
confirmatory batch, this changed behavior was large enough to improve realized
mission exposure.

The B1/B4 contrast is the more important practical comparison because B1 was the
legacy policy that previous predictive formulations struggled to beat. In the
1800-second batch, B4 improves over B1 with a paired confidence interval below
zero, which is stronger evidence than the earlier 900-second pilot.

## Thesis Claim Supported

The following claim is supported by the current confirmatory evidence:

> In habituating ground truth, the full habituation-aware STL predictive value
> function reduces value-weighted exposure relative to both legacy
> unconstrained dispatch and STL robustness without habituation. When
> habituation is disabled, the full STL system collapses to the no-habituation
> STL baseline, supporting the conclusion that the advantage comes from the
> habituation-aware clause.

## Generated Artifacts

Primary generated files:

- `results/testbench/habituation_stl_confirm_b1_b3_b4_1800s_10seed_v5/THESIS_RESULTS_SUMMARY.md`
- `results/testbench/habituation_stl_confirm_b1_b3_b4_1800s_10seed_v5/thesis_paired_comparisons.csv`
- `results/testbench/habituation_stl_confirm_b1_b3_b4_1800s_10seed_v5/thesis_core_summary.csv`

Figures:

- `results/testbench/habituation_stl_confirm_b1_b3_b4_1800s_10seed_v5/advisor_figures/exposure_mean_ci_by_system.png`
- `results/testbench/habituation_stl_confirm_b1_b3_b4_1800s_10seed_v5/advisor_figures/hab_on_exposure_per_seed.png`
- `results/testbench/habituation_stl_confirm_b1_b3_b4_1800s_10seed_v5/advisor_figures/hab_on_b4_paired_exposure_deltas.png`
- `results/testbench/habituation_stl_confirm_b1_b3_b4_1800s_10seed_v5/advisor_figures/hab_on_b4_b3_mechanism_deltas.png`

## Remaining Cautions

- The experiment is still simulation-only.
- The habituation model is stylized and should be described as a qualitative
  abstraction, not an ecological fit.
- The STL global robustness metric is stricter for B4 because B4 includes the
  habituation clause; exposure and mechanism metrics are the stronger evidence.
- Final thesis figures should use consistent styling with the rest of the
  experimental chapter.
