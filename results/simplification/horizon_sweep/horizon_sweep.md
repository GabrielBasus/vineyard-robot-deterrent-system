# Simplification Horizon Sweep

- Stages: s1_risk_open_core, s5_current_thesis_profile
- Horizons [h]: 2.000, 4.000, 6.000
- Main/current reference stage: `s5_current_thesis_profile`
- Runs per baseline: `3`
- Max workers: `6`

## Runtime

```text
                stage_key  horizon_h status  duration_s
        s1_risk_open_core        2.0     ok  547.329029
        s1_risk_open_core        4.0     ok 1259.561526
        s1_risk_open_core        6.0     ok 2052.576909
s5_current_thesis_profile        2.0     ok 1159.614849
s5_current_thesis_profile        4.0     ok 2293.778642
s5_current_thesis_profile        6.0     ok 3252.931820
```

## Horizon Summary

```text
                stage_key  horizon_h  proposed_vs_prediction_exposure_improve_pct  proposed_vs_reactive_exposure_improve_pct  proposed_birds_deterred_pct_mean  proposed_minus_prediction_birds_deterred_pct_pts  proposed_minus_reactive_birds_deterred_pct_pts  proposed_model_completed_mean  proposed_total_planner_rejections_mean
        s1_risk_open_core        2.0                                     1.805548                                   0.780399                          3.032289                                          2.672598                                        1.788642                      18.000000                            67432.666667
        s1_risk_open_core        4.0                                     4.676300                                   2.943940                          3.850249                                          3.424622                                        2.688950                     129.666667                           162903.333333
        s1_risk_open_core        6.0                                     5.509050                                   3.892835                          4.299165                                          3.907171                                        2.998669                     255.666667                           268685.666667
s5_current_thesis_profile        2.0                                     0.000000                                  -2.308282                          0.352824                                          0.000000                                       -1.081270                       0.000000                              548.000000
s5_current_thesis_profile        4.0                                     0.000000                                  -3.300788                          0.349396                                          0.000000                                       -1.016138                       0.000000                             1252.000000
s5_current_thesis_profile        6.0                                     0.000000                                  -1.440269                          0.406771                                          0.000000                                       -1.069500                       0.000000                             1901.666667
```

## Findings

- At `2.00 h`, best exposure vs prediction: `s1_risk_open_core` (1.806%).
- At `2.00 h`, highest birds deterred: `s1_risk_open_core` (3.032%).
- At `4.00 h`, best exposure vs prediction: `s1_risk_open_core` (4.676%).
- At `4.00 h`, highest birds deterred: `s1_risk_open_core` (3.850%).
- At `6.00 h`, best exposure vs prediction: `s1_risk_open_core` (5.509%).
- At `6.00 h`, highest birds deterred: `s1_risk_open_core` (4.299%).

## Stage Trends

- `s1_risk_open_core`: delta exposure vs prediction from shortest to longest horizon = 3.704 pts; delta birds deterred = 1.267 pts.
- `s5_current_thesis_profile`: delta exposure vs prediction from shortest to longest horizon = 0.000 pts; delta birds deterred = 0.054 pts.

## Recommendation

1. Use `s1_risk_open_core` as the next reference if the goal is horizon-robust exposure gain. Its best observed horizon is `6.00 h` with `5.509%` exposure improvement vs prediction.
1. Keep checking `s5_current_thesis_profile` across longer horizons only if its birds-deterred percentage or exposure trend improves materially. Current shortest-to-longest exposure delta is `0.000` pts.
1. Compare methods using the paired set of metrics: exposure, response time, birds deterred percentage, communication, and preventive completions. Do not choose a method based on birds deterred percentage alone.
