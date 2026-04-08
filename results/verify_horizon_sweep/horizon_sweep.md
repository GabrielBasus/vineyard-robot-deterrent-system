# Simplification Horizon Sweep

- Stages: s1_risk_open_core, s5_current_thesis_profile
- Horizons [h]: 0.050, 0.100
- Main/current reference stage: `s5_current_thesis_profile`
- Runs per baseline: `1`
- Max workers: `2`

## Runtime

```text
                stage_key  horizon_h status  duration_s
        s1_risk_open_core       0.05     ok    8.178033
        s1_risk_open_core       0.10     ok   11.147231
s5_current_thesis_profile       0.05     ok   10.879495
s5_current_thesis_profile       0.10     ok   18.938009
```

## Horizon Summary

```text
                stage_key  horizon_h  proposed_vs_prediction_exposure_improve_pct  proposed_vs_reactive_exposure_improve_pct  proposed_birds_deterred_pct_mean  proposed_minus_prediction_birds_deterred_pct_pts  proposed_minus_reactive_birds_deterred_pct_pts  proposed_model_completed_mean  proposed_total_planner_rejections_mean
        s1_risk_open_core       0.05                                     0.000000                                  -0.167375                          0.000000                                          0.000000                                        0.000000                            5.0                                   365.0
        s1_risk_open_core       0.10                                    11.073183                                   6.230424                         10.344828                                         10.344828                                        3.893215                            5.0                                  1101.0
s5_current_thesis_profile       0.05                                     0.000000                                  -0.167375                          0.000000                                          0.000000                                        0.000000                            0.0                                     1.0
s5_current_thesis_profile       0.10                                     0.000000                                  -5.445780                          0.000000                                          0.000000                                       -6.451613                            0.0                                    20.0
```

## Findings

- At `0.05 h`, best exposure vs prediction: `s1_risk_open_core` (0.000%).
- At `0.05 h`, highest birds deterred: `s1_risk_open_core` (0.000%).
- At `0.10 h`, best exposure vs prediction: `s1_risk_open_core` (11.073%).
- At `0.10 h`, highest birds deterred: `s1_risk_open_core` (10.345%).

## Stage Trends

- `s1_risk_open_core`: delta exposure vs prediction from shortest to longest horizon = 11.073 pts; delta birds deterred = 10.345 pts.
- `s5_current_thesis_profile`: delta exposure vs prediction from shortest to longest horizon = 0.000 pts; delta birds deterred = 0.000 pts.

## Recommendation

1. Use `s1_risk_open_core` as the next reference if the goal is horizon-robust exposure gain. Its best observed horizon is `0.10 h` with `11.073%` exposure improvement vs prediction.
1. Keep checking `s5_current_thesis_profile` across longer horizons only if its birds-deterred percentage or exposure trend improves materially. Current shortest-to-longest exposure delta is `0.000` pts.
1. Compare methods using the paired set of metrics: exposure, response time, birds deterred percentage, communication, and preventive completions. Do not choose a method based on birds deterred percentage alone.
