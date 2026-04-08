# Seeding Phase Comparison

Each job uses the existing `warmup_s` pre-run truth burn-in to seed SESTPP state, then resets public metrics before the scored horizon starts.

- Warmup values: `0, 60` seconds

## Best By System

### row_local_priority_queue: Row-Block Local Priority Queue
- Best exposure warmup: `0 s` with exposure `5.58` (delta vs no-warmup `0.00`).
- Best response warmup: `nan s` with response `nan s` (delta `nan s`).
- Best bird-deterrence warmup: `0 s` at `0.00%` (delta `0.00` pts).

### s1_risk_open_core: Main Core With Risk Gate Open
- Best exposure warmup: `0 s` with exposure `5.58` (delta vs no-warmup `0.00`).
- Best response warmup: `nan s` with response `nan s` (delta `nan s`).
- Best bird-deterrence warmup: `0 s` at `0.00%` (delta `0.00` pts).

## Runtime

```text
              system_key  warmup_s status  duration_s
       s1_risk_open_core       0.0     ok    6.424650
       s1_risk_open_core      60.0     ok    6.699390
row_local_priority_queue       0.0     ok    3.430407
row_local_priority_queue      60.0     ok    3.668589
```

## Summary

```text
              system_key  warmup_s  proposed_exposure_mean  delta_vs_no_warmup_exposure_mean  proposed_response_time_mean  delta_vs_no_warmup_response_time_mean  proposed_birds_deterred_pct_mean  delta_vs_no_warmup_birds_deterred_pct_pts  proposed_comm_mean  delta_vs_no_warmup_comm_mean  proposed_model_completed_mean  delta_vs_no_warmup_model_completed_mean
row_local_priority_queue       0.0                5.582665                          0.000000                          NaN                                    NaN                               0.0                                        0.0               128.0                           0.0                            0.0                                      0.0
row_local_priority_queue      60.0               14.320136                          8.737472                          NaN                                    NaN                               0.0                                        0.0               128.0                           0.0                            0.0                                      0.0
       s1_risk_open_core       0.0                5.582665                          0.000000                          NaN                                    NaN                               0.0                                        0.0                 0.0                           0.0                            1.0                                      0.0
       s1_risk_open_core      60.0               10.068856                          4.486191                          NaN                                    NaN                               0.0                                        0.0               128.0                         128.0                            0.0                                     -1.0
```

