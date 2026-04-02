# Component Diagnostic Report (Frozen vs Simple Task Management)

## Baselines Compared
- `reactive`: module=frozen, simulation_mode=reactive, simple_task_management=False
- `prediction_only`: module=frozen, simulation_mode=prediction_only, simple_task_management=False
- `proposed`: module=frozen, simulation_mode=proposed, simple_task_management=False
- `proposed_simple_tasks`: module=simple, simulation_mode=proposed, simple_task_management=True

## Final Metrics

| baseline              |   value_weighted_exposure |   mean_response_time_s |   boundary_message_count |   tasks_per_unit_distance |   fleet_task_engagement_fraction_so_far |   fleet_idle_no_task_fraction_so_far |   stale_goal_clears |   model_deterring_accepted |   model_deterring_generated |   model_deterring_candidates_total |
|:----------------------|--------------------------:|-----------------------:|-------------------------:|--------------------------:|----------------------------------------:|-------------------------------------:|--------------------:|---------------------------:|----------------------------:|-----------------------------------:|
| reactive              |                   529.452 |                138.256 |                       13 |                    0.0031 |                                  0.5968 |                               0.4032 |                   0 |                          0 |                           0 |                                  0 |
| prediction_only       |                   529.452 |                116.044 |                       17 |                    0.0048 |                                  0.914  |                               0.086  |                   0 |                          0 |                           0 |                                  0 |
| proposed              |                   529.452 |                111.91  |                       23 |                    0.0053 |                                  0.9677 |                               0.0323 |                   0 |                          6 |                           3 |                                 27 |
| proposed_simple_tasks |                   529.452 |                105.221 |                       25 |                    0.004  |                                  0.871  |                               0.129  |                   0 |                          1 |                           3 |                                 28 |

## Critical checks
- stale_goal_clears (simple - proposed): `0.000`
- proposed exposure improvement vs prediction_only: `0.000%`
- proposed_simple_tasks exposure improvement vs prediction_only: `0.000%`

## Output files
- `params.json`, `params_table.csv`
- `timeseries_*.csv`, `timeseries_all.csv`, `final_metrics_all.csv`, `zone_stats.csv`
- `01_zone_partition_paths_tasks.png`
- `02_model_internals_timeseries.png`
- `03_task_funnel_timeseries.png`
- `04_dispatch_diagnostics.png`
- `05_performance_compare.png`
- `06_delta_vs_prediction_over_time.png`