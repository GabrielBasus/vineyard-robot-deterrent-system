# Zone Partitioning Ablation Diagnostic

## Parameters

- `runs`: `2`
- `seed_start`: `2026`
- `mode_suite`: `both`
- `T_end`: `2400.0`
- `dt`: `5.0`
- `Nrobots`: `6`
- `uav_fraction`: `0.0`
- `warmup_s`: `1800.0`
- `task_replan_period_s`: `60.0`
- `patrol_hotspot_filter_mode`: `percentile`
- `patrol_hotspot_score_percentile`: `97.0`
- `alpha_inhib`: `0.45`
- `omega_inhib`: `600.0`
- `partition_scale`: `1500.0`
- `partition_gamma`: `1.0`

## Summary By Mode

### prediction_only

- `runs`: `2`
- `exposure_improve_pct_mean`: `0.42998480730327215`
- `exposure_improve_pct_std`: `0.6553395145418053`
- `response_improve_pct_mean`: `-1.3801746469966296`
- `response_improve_pct_std`: `3.668836901506549`
- `comm_increase_pct_mean`: `10.033167495854062`
- `delta_zone_area_cv_mean`: `0.002912239431817218`
- `delta_robot_util_std_mean`: `0.007426989690531106`
- `weighted_better_on_exposure_runs`: `1`
- `weighted_better_on_response_runs`: `1`

### proposed_feedback_only

- `runs`: `2`
- `exposure_improve_pct_mean`: `1.7174162436711056`
- `exposure_improve_pct_std`: `1.9427709509096387`
- `response_improve_pct_mean`: `-2.556622941634933`
- `response_improve_pct_std`: `2.4923886068682455`
- `comm_increase_pct_mean`: `8.404000869754295`
- `delta_zone_area_cv_mean`: `0.002912239431817218`
- `delta_robot_util_std_mean`: `-0.0004503676784352803`
- `weighted_better_on_exposure_runs`: `1`
- `weighted_better_on_response_runs`: `0`

## Conclusions

- prediction_only: current weighted partitioning has mixed effect relative to neutral Voronoi.
- proposed_feedback_only: current weighted partitioning has mixed effect relative to neutral Voronoi.
