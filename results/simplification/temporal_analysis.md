# Temporal Analysis

This report summarizes how stage performance changes with horizon length and across consecutive time bouts.

Main/current reference stage: `s5_current_thesis_profile`
Native bout window used in this report: `1800.0` s

## Stage Summary

```text
                stage_key  final_proposed_vs_prediction_exposure_improve_pct  final_proposed_vs_reactive_exposure_improve_pct  best_horizon_vs_prediction_h  best_horizon_vs_prediction_exposure_improve_pct  best_horizon_vs_reactive_h  best_horizon_vs_reactive_exposure_improve_pct  best_bout_vs_prediction_exposure_improve_pct  best_bout_vs_reactive_exposure_improve_pct  positive_bout_share_vs_prediction  positive_bout_share_vs_reactive  final_proposed_model_deterring_accepted_mean  final_proposed_model_deterring_generated_mean
     s0_simple_tasks_core                                           0.000000                                        -0.944497                      0.083333                                         0.000000                    0.083333                                       3.023051                                       0.00000                                    3.235946                                0.0                             0.25                                           0.0                                            0.0
             s1_main_core                                           0.000000                                        -0.998593                      0.083333                                         0.000000                    0.333333                                      -0.249914                                       0.00000                                    0.439138                                0.0                             0.50                                           0.0                                            0.0
        s1_risk_open_core                                           2.860082                                         1.890049                      0.166667                                         5.722406                    1.666667                                       2.604900                                       7.02846                                    5.656671                                1.0                             0.75                                          24.0                                          408.0
       s2_direct_conflict                                           0.000000                                        -0.998593                      0.083333                                         0.000000                    0.333333                                      -0.249914                                       0.00000                                    0.439138                                0.0                             0.50                                           0.0                                            0.0
           s3_persistence                                           0.000000                                        -0.998593                      0.083333                                         0.000000                    0.333333                                      -0.249914                                       0.00000                                    0.439138                                0.0                             0.50                                           0.0                                            0.0
       s4_capacity_budget                                           0.000000                                        -0.998593                      0.083333                                         0.000000                    0.333333                                      -0.249914                                       0.00000                                    0.439138                                0.0                             0.50                                           0.0                                            0.0
s5_current_thesis_profile                                           0.000000                                        -1.410997                      0.083333                                         0.000000                    0.083333                                       0.702604                                       0.00000                                    1.023591                                0.0                             0.50                                           0.0                                            0.0
```

## Stage Notes

### s0_simple_tasks_core: Simple Tasks Core
- Final horizon (2.00 h): vs prediction=0.000%, vs reactive=-0.944%.
- Best cumulative horizon: vs prediction=0.000% at 0.08 h; vs reactive=3.023% at 0.08 h.
- Best time bout: vs prediction=0.000% from 0.00 to 0.50 h; vs reactive=3.236% from 0.50 to 1.00 h.
- Positive-bout share: vs prediction=0.000%, vs reactive=25.000%.
- Horizon trend: vs prediction roughly stable; vs reactive strengthens late.
- Preventive activity by final horizon: generated=0.000, accepted=0.000, completed_tasks=839.800.

### s1_main_core: Main Runtime Core
- Final horizon (2.00 h): vs prediction=0.000%, vs reactive=-0.999%.
- Best cumulative horizon: vs prediction=0.000% at 0.08 h; vs reactive=-0.250% at 0.33 h.
- Best time bout: vs prediction=0.000% from 0.00 to 0.50 h; vs reactive=0.439% from 1.50 to 2.00 h.
- Positive-bout share: vs prediction=0.000%, vs reactive=50.000%.
- Horizon trend: vs prediction roughly stable; vs reactive strengthens late.
- Preventive activity by final horizon: generated=0.000, accepted=0.000, completed_tasks=247.000.

### s1_risk_open_core: Main Core With Risk Gate Open
- Final horizon (2.00 h): vs prediction=2.860%, vs reactive=1.890%.
- Best cumulative horizon: vs prediction=5.722% at 0.17 h; vs reactive=2.605% at 1.67 h.
- Best time bout: vs prediction=7.028% from 0.50 to 1.00 h; vs reactive=5.657% from 0.50 to 1.00 h.
- Positive-bout share: vs prediction=100.000%, vs reactive=75.000%.
- Horizon trend: vs prediction strengthens late; vs reactive strengthens late.
- Preventive activity by final horizon: generated=408.000, accepted=24.000, completed_tasks=291.200.

### s2_direct_conflict: Add Direct Conflict Guard
- Final horizon (2.00 h): vs prediction=0.000%, vs reactive=-0.999%.
- Best cumulative horizon: vs prediction=0.000% at 0.08 h; vs reactive=-0.250% at 0.33 h.
- Best time bout: vs prediction=0.000% from 0.00 to 0.50 h; vs reactive=0.439% from 1.50 to 2.00 h.
- Positive-bout share: vs prediction=0.000%, vs reactive=50.000%.
- Horizon trend: vs prediction roughly stable; vs reactive strengthens late.
- Preventive activity by final horizon: generated=0.000, accepted=0.000, completed_tasks=247.000.

### s3_persistence: Add Persistence Locks
- Final horizon (2.00 h): vs prediction=0.000%, vs reactive=-0.999%.
- Best cumulative horizon: vs prediction=0.000% at 0.08 h; vs reactive=-0.250% at 0.33 h.
- Best time bout: vs prediction=0.000% from 0.00 to 0.50 h; vs reactive=0.439% from 1.50 to 2.00 h.
- Positive-bout share: vs prediction=0.000%, vs reactive=50.000%.
- Horizon trend: vs prediction roughly stable; vs reactive strengthens late.
- Preventive activity by final horizon: generated=0.000, accepted=0.000, completed_tasks=247.000.

### s4_capacity_budget: Add Capacity And Budget
- Final horizon (2.00 h): vs prediction=0.000%, vs reactive=-0.999%.
- Best cumulative horizon: vs prediction=0.000% at 0.08 h; vs reactive=-0.250% at 0.33 h.
- Best time bout: vs prediction=0.000% from 0.00 to 0.50 h; vs reactive=0.439% from 1.50 to 2.00 h.
- Positive-bout share: vs prediction=0.000%, vs reactive=50.000%.
- Horizon trend: vs prediction roughly stable; vs reactive strengthens late.
- Preventive activity by final horizon: generated=0.000, accepted=0.000, completed_tasks=247.000.

### s5_current_thesis_profile: Current Thesis Profile
- Final horizon (2.00 h): vs prediction=0.000%, vs reactive=-1.411%.
- Best cumulative horizon: vs prediction=0.000% at 0.08 h; vs reactive=0.703% at 0.08 h.
- Best time bout: vs prediction=0.000% from 0.00 to 0.50 h; vs reactive=1.024% from 0.50 to 1.00 h.
- Positive-bout share: vs prediction=0.000%, vs reactive=50.000%.
- Horizon trend: vs prediction roughly stable; vs reactive strengthens late.
- Preventive activity by final horizon: generated=0.000, accepted=0.000, completed_tasks=241.000.
