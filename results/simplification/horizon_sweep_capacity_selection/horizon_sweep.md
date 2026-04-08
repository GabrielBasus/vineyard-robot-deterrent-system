# Simplification Horizon Sweep

- Stages: s1_capacity_aware_selection_core, s1_risk_open_core
- Horizons [h]: 4.000, 6.000
- Main/current reference stage: `s5_current_thesis_profile`
- Runs per baseline: `3`
- Max workers: `4`

## Runtime

```text
                       stage_key  horizon_h status  duration_s
               s1_risk_open_core        4.0     ok  749.588823
               s1_risk_open_core        6.0     ok 1062.854287
s1_capacity_aware_selection_core        4.0     ok 1115.568330
s1_capacity_aware_selection_core        6.0     ok 1414.829444
```

## Horizon Summary

```text
                       stage_key  horizon_h  proposed_vs_prediction_exposure_improve_pct  proposed_vs_reactive_exposure_improve_pct  proposed_birds_deterred_pct_mean  proposed_minus_prediction_birds_deterred_pct_pts  proposed_minus_reactive_birds_deterred_pct_pts  proposed_model_completed_mean  proposed_total_planner_rejections_mean
               s1_risk_open_core        4.0                                     4.676300                                   2.943940                          3.850249                                          3.424622                                        2.688950                     129.666667                           162903.333333
               s1_risk_open_core        6.0                                     5.509050                                   3.892835                          4.299165                                          3.907171                                        2.998669                     255.666667                           268685.666667
s1_capacity_aware_selection_core        4.0                                     0.128987                                  -2.035700                          0.603795                                          0.342580                                       -0.557505                       1.333333                             2727.333333
s1_capacity_aware_selection_core        6.0                                     0.757197                                  -1.539945                          0.639634                                          0.373052                                       -0.660862                       2.000000                             4070.333333
```

## Findings

- At `4.00 h`, best exposure vs prediction: `s1_risk_open_core` (4.676%).
- At `4.00 h`, highest birds deterred: `s1_risk_open_core` (3.850%).
- At `6.00 h`, best exposure vs prediction: `s1_risk_open_core` (5.509%).
- At `6.00 h`, highest birds deterred: `s1_risk_open_core` (4.299%).

## Stage Trends

- `s1_risk_open_core`: delta exposure vs prediction from shortest to longest horizon = 0.833 pts; delta birds deterred = 0.449 pts.
- `s1_capacity_aware_selection_core`: delta exposure vs prediction from shortest to longest horizon = 0.628 pts; delta birds deterred = 0.036 pts.

## Recommendation

1. Use `s1_risk_open_core` as the next reference if the goal is horizon-robust exposure gain. Its best observed horizon is `6.00 h` with `5.509%` exposure improvement vs prediction.
1. Compare methods using the paired set of metrics: exposure, response time, birds deterred percentage, communication, and preventive completions. Do not choose a method based on birds deterred percentage alone.
