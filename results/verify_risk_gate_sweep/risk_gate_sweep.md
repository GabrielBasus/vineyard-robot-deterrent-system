# Risk Gate Sweep

- Base stage: `s1_main_core`
- Base/current variant: `s1_main_core__thr_0p35__scale_0p0001`
- Runs per baseline: `1`
- Horizon: `60.0` s
- Max workers: `2`

## Runtime

```text
                         output_name status  duration_s
   s1_main_core__thr_0__scale_0p0001     ok    4.986890
s1_main_core__thr_0p35__scale_0p0001     ok    5.113948
```

## Variant Summary

```text
                         output_name  risk_threshold  risk_scale  proposed_vs_prediction_exposure_improve_pct  proposed_vs_reactive_exposure_improve_pct  risk_rejection_rate  risk_pass_rate  generated_mean  accepted_mean  completed_model_scored_mean  planner_rejections_total_mean
   s1_main_core__thr_0__scale_0p0001            0.00      0.0001                                          0.0                                        0.0                  0.0        0.642857             8.0            3.0                          1.0                           41.0
s1_main_core__thr_0p35__scale_0p0001            0.35      0.0001                                          0.0                                        0.0                  1.0        0.000000             0.0            0.0                          0.0                           27.0
```

## Findings

- Best generation variant: `s1_main_core__thr_0__scale_0p0001` (generated=8.000, accepted=3.000, completed=1.000).
- Best completion variant: `s1_main_core__thr_0__scale_0p0001` (completed=1.000, exposure vs prediction=0.000%).
- Lowest risk-rejection rate: `s1_main_core__thr_0__scale_0p0001` (threshold=0.000, scale=0.000100, risk_rejection_rate=0.000, generated=8.000).

## Recommended Next Steps

1. Use the best completion variant as the new debugging base and then inspect dispatch protection / queue pressure only after the risk gate is confirmed open.
1. Rerun the promising risk variant `s1_main_core__thr_0__scale_0p0001` at the full thesis horizon after this sweep, because it minimizes risk rejection relative to the current setting.
