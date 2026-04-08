# Risk Gate Sweep

- Base stage: `s1_main_core`
- Base/current variant: `s1_main_core__thr_0p35__scale_0p0001`
- Runs per baseline: `3`
- Horizon: `3600.0` s
- Max workers: `16`

## Runtime

```text
                         output_name status  duration_s
   s1_main_core__thr_0__scale_0p0001     ok  264.006344
 s1_main_core__thr_0p1__scale_0p0001     ok  515.073801
 s1_main_core__thr_0p35__scale_0p001     ok  516.602887
s1_main_core__thr_0p35__scale_0p0005     ok  517.291456
s1_main_core__thr_0p35__scale_0p0002     ok  517.887265
s1_main_core__thr_0p05__scale_0p0001     ok  519.624423
s1_main_core__thr_0p35__scale_0p0001     ok  522.953553
 s1_main_core__thr_0p2__scale_0p0001     ok  538.749817
```

## Variant Summary

```text
                         output_name  risk_threshold  risk_scale  proposed_vs_prediction_exposure_improve_pct  proposed_vs_reactive_exposure_improve_pct  risk_rejection_rate  risk_pass_rate  generated_mean  accepted_mean  completed_model_scored_mean  planner_rejections_total_mean
   s1_main_core__thr_0__scale_0p0001            0.00      0.0001                                     4.539466                                  -0.008290             0.000000        0.866032      257.000000           17.0                         14.0                   26003.333333
s1_main_core__thr_0p05__scale_0p0001            0.05      0.0001                                     1.366387                                  -3.332535             0.690356        0.240914      214.333333           30.0                         26.0                   29985.000000
 s1_main_core__thr_0p1__scale_0p0001            0.10      0.0001                                     0.000000                                  -4.764017             0.997980        0.000000        0.000000            0.0                          0.0                   30101.666667
 s1_main_core__thr_0p2__scale_0p0001            0.20      0.0001                                     0.000000                                  -4.764017             0.997980        0.000000        0.000000            0.0                          0.0                   30101.666667
s1_main_core__thr_0p35__scale_0p0001            0.35      0.0001                                     0.000000                                  -4.764017             0.997980        0.000000        0.000000            0.0                          0.0                   30101.666667
s1_main_core__thr_0p35__scale_0p0002            0.35      0.0002                                     0.000000                                  -4.764017             0.997980        0.000000        0.000000            0.0                          0.0                   30101.666667
s1_main_core__thr_0p35__scale_0p0005            0.35      0.0005                                     0.000000                                  -4.764017             0.997980        0.000000        0.000000            0.0                          0.0                   30101.666667
 s1_main_core__thr_0p35__scale_0p001            0.35      0.0010                                     0.000000                                  -4.764017             0.997980        0.000000        0.000000            0.0                          0.0                   30101.666667
```

## Findings

- Best generation variant: `s1_main_core__thr_0__scale_0p0001` (generated=257.000, accepted=17.000, completed=14.000).
- Best completion variant: `s1_main_core__thr_0p05__scale_0p0001` (completed=26.000, exposure vs prediction=1.366%).
- Lowest risk-rejection rate: `s1_main_core__thr_0__scale_0p0001` (threshold=0.000, scale=0.000100, risk_rejection_rate=0.000, generated=257.000).

## Recommended Next Steps

1. Use the best completion variant as the new debugging base and then inspect dispatch protection / queue pressure only after the risk gate is confirmed open.
1. Rerun the promising risk variant `s1_main_core__thr_0__scale_0p0001` at the full thesis horizon after this sweep, because it minimizes risk rejection relative to the current setting.
