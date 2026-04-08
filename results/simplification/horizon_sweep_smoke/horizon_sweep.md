# Simplification Horizon Sweep

- Stages: s1_risk_open_core, s5_current_thesis_profile
- Horizons [h]: 0.500, 1.000
- Main/current reference stage: `s5_current_thesis_profile`
- Runs per baseline: `1`
- Max workers: `2`

## Runtime

```text
                stage_key  horizon_h status  duration_s
        s1_risk_open_core        0.5     ok   38.119853
        s1_risk_open_core        1.0     ok   67.116343
s5_current_thesis_profile        0.5     ok   61.953627
s5_current_thesis_profile        1.0     ok  111.242672
```

## Horizon Summary

```text
                stage_key  horizon_h  proposed_vs_prediction_exposure_improve_pct  proposed_vs_reactive_exposure_improve_pct  proposed_birds_deterred_pct_mean  proposed_minus_prediction_birds_deterred_pct_pts  proposed_minus_reactive_birds_deterred_pct_pts  proposed_model_completed_mean  proposed_total_planner_rejections_mean
        s1_risk_open_core        0.5                                     3.369746                                  -7.783882                          6.578947                                          6.578947                                        3.007519                            6.0                                 11463.0
        s1_risk_open_core        1.0                                    11.042947                                   3.459984                          6.884058                                          6.884058                                        4.686256                           16.0                                 31578.0
s5_current_thesis_profile        0.5                                     0.000000                                 -12.168182                          1.333333                                          0.000000                                       -2.238095                            0.0                                   141.0
s5_current_thesis_profile        1.0                                     0.000000                                  -9.235032                          0.675676                                          0.000000                                       -1.522127                            0.0                                   329.0
```

## Findings

- At `0.50 h`, best exposure vs prediction: `s1_risk_open_core` (3.370%).
- At `0.50 h`, highest birds deterred: `s1_risk_open_core` (6.579%).
- At `1.00 h`, best exposure vs prediction: `s1_risk_open_core` (11.043%).
- At `1.00 h`, highest birds deterred: `s1_risk_open_core` (6.884%).

## Stage Trends

- `s1_risk_open_core`: delta exposure vs prediction from shortest to longest horizon = 7.673 pts; delta birds deterred = 0.305 pts.
- `s5_current_thesis_profile`: delta exposure vs prediction from shortest to longest horizon = 0.000 pts; delta birds deterred = -0.658 pts.

## Recommendation

1. Use `s1_risk_open_core` as the next reference if the goal is horizon-robust exposure gain. Its best observed horizon is `1.00 h` with `11.043%` exposure improvement vs prediction.
1. Keep checking `s5_current_thesis_profile` across longer horizons only if its birds-deterred percentage or exposure trend improves materially. Current shortest-to-longest exposure delta is `0.000` pts.
1. Compare methods using the paired set of metrics: exposure, response time, birds deterred percentage, communication, and preventive completions. Do not choose a method based on birds deterred percentage alone.
