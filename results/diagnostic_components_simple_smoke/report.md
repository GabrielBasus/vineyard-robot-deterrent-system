# Component Diagnostic Report (Frozen vs Simple Task Management)

## Baselines Compared
- `reactive`: module=frozen, simulation_mode=reactive, simple_task_management=False
- `prediction_only`: module=frozen, simulation_mode=prediction_only, simple_task_management=False
- `proposed`: module=frozen, simulation_mode=proposed, simple_task_management=False
- `proposed_simple_tasks`: module=simple, simulation_mode=proposed, simple_task_management=True

## Final Metrics

| baseline              |   value_weighted_exposure |   mean_response_time_s |   boundary_message_count |   tasks_per_unit_distance |   fleet_task_engagement_fraction_so_far |   fleet_idle_no_task_fraction_so_far |   stale_goal_clears |   model_deterring_accepted |   model_deterring_generated |   model_deterring_candidates_total |
|:----------------------|--------------------------:|-----------------------:|-------------------------:|--------------------------:|----------------------------------------:|-------------------------------------:|--------------------:|---------------------------:|----------------------------:|-----------------------------------:|
| reactive              |                   1061.3  |                177.868 |                       23 |                    0.0049 |                                  0.724  |                               0.276  |                   0 |                          0 |                           0 |                                  0 |
| prediction_only       |                   1052.22 |                103.409 |                       18 |                    0.0069 |                                  0.9208 |                               0.0792 |                   0 |                          0 |                           0 |                                  0 |
| proposed              |                   1036.27 |                106.103 |                       25 |                    0.0082 |                                  0.8552 |                               0.1448 |                   0 |                          5 |                           2 |                                 45 |
| proposed_simple_tasks |                   1052.22 |                102.008 |                       36 |                    0.005  |                                  0.8197 |                               0.1803 |                   0 |                          4 |                           3 |                                 54 |

## Critical checks
- stale_goal_clears (simple - proposed): `0.000`
- proposed exposure improvement vs prediction_only: `1.515%`
- proposed_simple_tasks exposure improvement vs prediction_only: `0.000%`

## Output files
- `params.json`, `params_table.csv`
- `timeseries_*.csv`, `timeseries_all.csv`, `final_metrics_all.csv`, `zone_stats.csv`
- `01_zone_partition_paths_tasks.png`
- `02_model_internals_timeseries.png`
- `03_task_funnel_timeseries.png`
- `04_dispatch_diagnostics.png`
- `05_performance_compare.png`