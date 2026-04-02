# Component Diagnostic Report (Frozen vs Simple Task Management)

## Baselines Compared
- `reactive`: module=frozen, simulation_mode=reactive, simple_task_management=False
- `prediction_only`: module=frozen, simulation_mode=prediction_only, simple_task_management=False
- `proposed`: module=frozen, simulation_mode=proposed, simple_task_management=False
- `proposed_simple_tasks`: module=simple, simulation_mode=proposed, simple_task_management=True

## Final Metrics

| baseline              |   value_weighted_exposure |   mean_response_time_s |   boundary_message_count |   tasks_per_unit_distance |   fleet_task_engagement_fraction_so_far |   fleet_idle_no_task_fraction_so_far |   stale_goal_clears |   model_deterring_accepted |   model_deterring_generated |   model_deterring_candidates_total |
|:----------------------|--------------------------:|-----------------------:|-------------------------:|--------------------------:|----------------------------------------:|-------------------------------------:|--------------------:|---------------------------:|----------------------------:|-----------------------------------:|
| reactive              |                   17872.7 |                103.045 |                      528 |                    0.0105 |                                  0.3186 |                               0.6814 |                   0 |                          0 |                           0 |                                  0 |
| prediction_only       |                   17633.1 |                182.635 |                      248 |                    0.0128 |                                  0.7888 |                               0.2112 |                   0 |                          0 |                           0 |                                  0 |
| proposed              |                   17767.1 |                198.553 |                      477 |                    0.0129 |                                  0.7812 |                               0.2188 |                   0 |                         19 |                          10 |                                955 |
| proposed_simple_tasks |                   17265.3 |                166.147 |                      687 |                    0.0093 |                                  0.7095 |                               0.2905 |                   5 |                         18 |                          14 |                                991 |

## Critical checks
- stale_goal_clears (simple - proposed): `5.000`
- proposed exposure improvement vs prediction_only: `-0.760%`
- proposed_simple_tasks exposure improvement vs prediction_only: `2.086%`

## Output files
- `params.json`, `params_table.csv`
- `timeseries_*.csv`, `timeseries_all.csv`, `final_metrics_all.csv`, `zone_stats.csv`
- `01_zone_partition_paths_tasks.png`
- `02_model_internals_timeseries.png`
- `03_task_funnel_timeseries.png`
- `04_dispatch_diagnostics.png`
- `05_performance_compare.png`
- `06_delta_vs_prediction_over_time.png`