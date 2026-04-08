# Local Queue Weight Sweep

- Base variant: `row_local_priority_queue`
- Risk-open setting: threshold=`0.0000` scale=`0.000100`
- Runs per baseline: `1`
- Horizon: `60.0` s

## Highlights

- Best exposure: `row_local_priority_queue__risk_open__distance_0p02` at `5.583` with `0.000%` vs reactive.
- Best bird deterrence: `row_local_priority_queue__risk_open__distance_0p02` at `0.000%`.
- Best overall rank: `row_local_priority_queue__risk_open__distance_0p02` with `1.000`.

## Runtime

```text
                                            output_name          family status  duration_s
     row_local_priority_queue__risk_open__distance_0p02        distance     ok    1.297977
              row_local_priority_queue__risk_open__base            base     ok    1.304977
row_local_priority_queue__risk_open__deterring_bonus_12 deterring_bonus     ok    1.266179
```

## Sweep Summary

```text
                                            output_name          family  param_value  proposed_vs_prediction_exposure_improve_pct  proposed_vs_reactive_exposure_improve_pct  proposed_response_time_mean  proposed_birds_deterred_pct_mean  proposed_comm_mean  proposed_model_completed_mean  proposed_total_planner_rejections_mean
     row_local_priority_queue__risk_open__distance_0p02        distance         0.02                                          0.0                                        0.0                          NaN                               0.0               128.0                            0.0                                     0.0
              row_local_priority_queue__risk_open__base            base          NaN                                          0.0                                        0.0                          NaN                               0.0               128.0                            0.0                                     0.0
row_local_priority_queue__risk_open__deterring_bonus_12 deterring_bonus        12.00                                          0.0                                        0.0                          NaN                               0.0               128.0                            0.0                                     0.0
```

## Recommended Next Step

1. Treat `row_local_priority_queue__risk_open__distance_0p02` as the next exploratory candidate and compare it directly against `s1_risk_open_core` using `exploration.compare_system_performance` after promoting its settings into a named exploration variant.
