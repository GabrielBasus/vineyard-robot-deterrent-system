# Pluggable Testbench

This report evaluates all configured systems under the same scenario and metric contract.

## Repositories

- current: `C:\Users\gabri\Documents\CalPoly\Thesis\Code`
- current branch: `snapshot/intervention-refactor-planner-diagnostics-20260401`
- current commit: `cbfbfc898d83455806d72d9341830357a1e699c3`
- current dirty: `True`
- main: `C:\Users\gabri\Documents\CalPoly\Thesis\Code-main`
- main branch: `main`
- main commit: `950adbabb055cc1e470c44efb3e0a165f16f3904`
- main dirty: `False`

## Scenario

- `H`: `500.0`
- `NX`: `120`
- `NY`: `96`
- `Nrobots`: `6`
- `W`: `500.0`
- `arrival_radius_m`: `3.0`
- `dt`: `1.0`
- `duration_s`: `3600.0`
- `fps`: `1`
- `hold_time_s`: `20.0`
- `num_runs`: `3`
- `sample_every_s`: `300.0`
- `seed_start`: `123`
- `task_replan_period_s`: `45.0`
- `uav_fraction`: `0.0`
- `warmup_s`: `0.0`

## Systems

- `outline_core`: Outline Core
  kind=`simplification_stage` module=`DeterrentSystem` repo=`C:\Users\gabri\Documents\CalPoly\Thesis\Code`
  Simplification stage s1_risk_open_core: Same stripped-down main runtime as stage 1, but with the heuristic preventive risk threshold fixed at 0.0 so the model-scored preventive branch is active and can be debugged before later protection layers are added back.
- `exploration_local_queue`: Exploration Local Queue
  kind=`exploration_variant` module=`exploration.row_local_priority_system` repo=`C:\Users\gabri\Documents\CalPoly\Thesis\Code`
  Whole-row partitioning with live-pose row ownership and per-robot local priority queues instead of global assignment.
- `current_prediction`: Current Prediction Only
  kind=`current_mode` module=`DeterrentSystem` repo=`C:\Users\gabri\Documents\CalPoly\Thesis\Code`
  Current workspace mode prediction_only.
- `current_reactive`: Current Reactive
  kind=`current_mode` module=`DeterrentSystem` repo=`C:\Users\gabri\Documents\CalPoly\Thesis\Code`
  Current workspace mode reactive.

## Output Contract

- reference system: `outline_core`
- summarized metrics: `native_value_weighted_exposure, native_mean_response_time_s, native_birds_deterred_pct_last_hour, completed_tasks_total, completed_deterring_total, tasks_per_km_travel, native_boundary_message_count`
- scoreboard metrics: `native_value_weighted_exposure, native_mean_response_time_s, native_birds_deterred_pct_last_hour, completed_tasks_total, native_boundary_message_count`
- time-plot metrics: `native_value_weighted_exposure, native_mean_response_time_s, native_birds_deterred_pct_last_hour, completed_deterring_total, completed_tasks_total, active_tasks`

## Scoreboard

| system                  |   metric_wins |   win_share |
|:------------------------|--------------:|------------:|
| exploration_local_queue |             2 |         0.4 |
| outline_core            |             2 |         0.4 |
| current_prediction      |             1 |         0.2 |
| current_reactive        |             0 |         0   |

## Metric Summary

| Metric                       | Goal   | outline_core                  | exploration_local_queue       | current_prediction            | current_reactive              | Winner                  |
|:-----------------------------|:-------|:------------------------------|:------------------------------|:------------------------------|:------------------------------|:------------------------|
| Value-Weighted Exposure      | lower  | 5518.265 [5224.742, 5811.787] | 5600.134 [5439.822, 5760.446] | 5672.486 [5508.326, 5836.647] | 5647.399 [5362.028, 5932.771] | outline_core            |
| Mean Response Time (s)       | lower  | 128.843 [33.087, 224.600]     | 75.150 [64.064, 86.236]       | 81.984 [70.894, 93.073]       | 125.197 [107.978, 142.417]    | exploration_local_queue |
| Last-Hour Birds Deterred (%) | higher | 0.686 [0.533, 0.838]          | 0.143 [0.077, 0.210]          | 0.154 [0.111, 0.196]          | 0.139 [0.034, 0.245]          | outline_core            |
| Completed Tasks              | higher | 96.667 [36.040, 157.293]      | 279.000 [270.457, 287.543]    | 80.667 [69.793, 91.540]       | 10.000 [4.814, 15.186]        | exploration_local_queue |
| Completed Deterring          | higher | 21.667 [18.819, 24.514]       | 8.000 [3.920, 12.080]         | 7.667 [5.938, 9.395]          | 10.000 [4.814, 15.186]        | outline_core            |
| Tasks / km Travel            | higher | 2.283 [0.487, 4.079]          | 6.053 [5.662, 6.444]          | 1.769 [1.479, 2.060]          | 3.363 [1.599, 5.127]          | exploration_local_queue |
| Boundary Message Count       | lower  | 18.000 [14.080, 21.920]       | 16.333 [6.709, 25.958]        | 10.333 [2.971, 17.696]        | 14.667 [11.210, 18.124]       | current_prediction      |

Positive advantage means the listed system outperformed `outline_core` after accounting for metric direction.

## Advantage Vs Reference

| Metric                       | exploration_local_queue vs outline_core advantage %   | current_prediction vs outline_core advantage %   | current_reactive vs outline_core advantage %   |
|:-----------------------------|:------------------------------------------------------|:-------------------------------------------------|:-----------------------------------------------|
| Value-Weighted Exposure      | -1.551 [-4.002, 0.899]                                | -2.869 [-5.786, 0.048]                           | -2.379 [-6.057, 1.299]                         |
| Mean Response Time (s)       | 23.814 [-26.585, 74.212]                              | 17.368 [-31.763, 66.499]                         | -18.776 [-74.687, 37.135]                      |
| Last-Hour Birds Deterred (%) | -78.236 [-89.544, -66.929]                            | -76.274 [-88.333, -64.215]                       | -77.366 [-98.614, -56.118]                     |
| Completed Tasks              | 245.496 [69.975, 421.018]                             | -3.292 [-46.506, 39.922]                         | -89.011 [-93.253, -84.769]                     |
| Completed Deterring          | -63.816 [-80.245, -47.387]                            | -64.726 [-70.337, -59.115]                       | -55.004 [-72.952, -37.056]                     |
| Tasks / km Travel            | 247.155 [46.293, 448.018]                             | -2.319 [-55.337, 50.699]                         | 61.951 [22.270, 101.632]                       |
| Boundary Message Count       | 3.598 [-64.270, 71.467]                               | 41.098 [-6.725, 88.921]                          | 15.152 [-17.742, 48.045]                       |

## Artifacts

- `per_run_metrics.csv`: one row per system per seed
- `per_run_timeseries.csv`: sampled trajectory metrics when available
- `summary_by_metric.csv`: aggregate means, CI95, and paired deltas vs the reference system
- `trajectory_compare.png`: generic backlog/completion trajectories
- `time_metric_compare.png`: time-series comparison for the selected result metrics
- `system_scoreboard.csv`: metric win counts on the selected scoreboard metric set
- `testbench_manifest.json`: resolved config and target metadata
- `report.md`: this summary
