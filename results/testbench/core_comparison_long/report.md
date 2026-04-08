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
- `duration_s`: `14400.0`
- `fps`: `1`
- `hold_time_s`: `20.0`
- `num_runs`: `5`
- `sample_every_s`: `300.0`
- `seed_start`: `123`
- `task_replan_period_s`: `45.0`
- `uav_fraction`: `0.0`
- `warmup_s`: `0.0`

## Systems

- `s0_simple_tasks_core`: S0 Simple Tasks Core
  kind=`simplification_stage` module=`DeterrentSystem_simple_tasks` repo=`C:\Users\gabri\Documents\CalPoly\Thesis\Code`
  Simplification stage s0_simple_tasks_core: Smallest end-to-end thesis-consistent branch already present in the repo: zone partitioning, SESTPP feedback, hotspot tasks, preventive tasks, and simple one-task-per-robot management.
- `s1_main_core`: S1 Main Core
  kind=`simplification_stage` module=`DeterrentSystem` repo=`C:\Users\gabri\Documents\CalPoly\Thesis\Code`
  Simplification stage s1_main_core: Main runtime with the same stripped-down planner idea as stage 0: heuristic preventive admission, no protective dispatch heuristics, no capacity throttles, and minimal queueing.
- `s1_risk_open_core`: S1 Risk Open Core
  kind=`simplification_stage` module=`DeterrentSystem` repo=`C:\Users\gabri\Documents\CalPoly\Thesis\Code`
  Simplification stage s1_risk_open_core: Same stripped-down main runtime as stage 1, but with the heuristic preventive risk threshold fixed at 0.0 so the model-scored preventive branch is active and can be debugged before later protection layers are added back.
- `s1_capacity_aware_selection_core`: S1 Capacity-Aware Selection
  kind=`simplification_stage` module=`DeterrentSystem` repo=`C:\Users\gabri\Documents\CalPoly\Thesis\Code`
  Simplification stage s1_capacity_aware_selection_core: Keeps the risk-open main core but replaces pass-through pre-assignment admission with a capacity-aware greedy selector that reserves direct detections and then admits the best marginal-gain-per-cost tasks.
- `s2_direct_conflict`: S2 Direct Conflict
  kind=`simplification_stage` module=`DeterrentSystem` repo=`C:\Users\gabri\Documents\CalPoly\Thesis\Code`
  Simplification stage s2_direct_conflict: Adds only the rule that model-scored preventive tasks must not conflict with active or recent direct-detection work.
- `s3_persistence`: S3 Persistence
  kind=`simplification_stage` module=`DeterrentSystem` repo=`C:\Users\gabri\Documents\CalPoly\Thesis\Code`
  Simplification stage s3_persistence: Adds preventive persistence so admitted model-scored tasks are not dropped immediately on the next replan.
- `s4_capacity_budget`: S4 Capacity Budget
  kind=`simplification_stage` module=`DeterrentSystem` repo=`C:\Users\gabri\Documents\CalPoly\Thesis\Code`
  Simplification stage s4_capacity_budget: Adds the throttling layer: per-robot preventive budgets, service-rate capacity gating, cycle admission caps, and strict busy-robot fallback.
- `s5_current_thesis_profile`: S5 Current Thesis Profile
  kind=`simplification_stage` module=`DeterrentSystem` repo=`C:\Users\gabri\Documents\CalPoly\Thesis\Code`
  Simplification stage s5_current_thesis_profile: Current thesis-facing proposed runtime: frozen calibration plus the named planner profile used for thesis confirmation work.
- `main_native`: Main Native
  kind=`repo_module` module=`DeterrentSystem` repo=`C:\Users\gabri\Documents\CalPoly\Thesis\Code-main`
  Module target DeterrentSystem in C:\Users\gabri\Documents\CalPoly\Thesis\Code-main.
- `row_local_priority_queue`: Row Local Priority Queue
  kind=`exploration_variant` module=`exploration.row_local_priority_system` repo=`C:\Users\gabri\Documents\CalPoly\Thesis\Code`
  Whole-row partitioning with live-pose row ownership and per-robot local priority queues instead of global assignment.
- `row_local_priority_queue_frequent_repartition`: Row Local Priority Queue Frequent Repartition
  kind=`exploration_variant` module=`exploration.row_local_priority_system` repo=`C:\Users\gabri\Documents\CalPoly\Thesis\Code`
  Same local row queues, but zones are recomputed aggressively from live pose and queue scoring penalizes distance more strongly.

## Output Contract

- reference system: `s1_risk_open_core`
- summarized metrics: `native_value_weighted_exposure, native_mean_response_time_s, native_birds_deterred_pct_last_hour, completed_tasks_total, completed_deterring_total, tasks_per_km_travel, native_boundary_message_count`
- scoreboard metrics: `native_value_weighted_exposure, native_mean_response_time_s, native_birds_deterred_pct_last_hour, completed_deterring_total`
- time-plot metrics: `native_value_weighted_exposure, native_mean_response_time_s, native_birds_deterred_pct_last_hour, completed_deterring_total, completed_tasks_total, active_tasks`

## Scoreboard

| system                                        |   metric_wins |   win_share |
|:----------------------------------------------|--------------:|------------:|
| s1_risk_open_core                             |             2 |        0.5  |
| main_native                                   |             1 |        0.25 |
| row_local_priority_queue_frequent_repartition |             1 |        0.25 |
| row_local_priority_queue                      |             0 |        0    |
| s0_simple_tasks_core                          |             0 |        0    |
| s1_capacity_aware_selection_core              |             0 |        0    |
| s1_main_core                                  |             0 |        0    |
| s2_direct_conflict                            |             0 |        0    |
| s3_persistence                                |             0 |        0    |
| s4_capacity_budget                            |             0 |        0    |
| s5_current_thesis_profile                     |             0 |        0    |

## Metric Summary

| Metric                       | Goal   | s0_simple_tasks_core             | s1_main_core                     | s1_risk_open_core                | s1_capacity_aware_selection_core   | s2_direct_conflict               | s3_persistence                   | s4_capacity_budget               | s5_current_thesis_profile        | main_native                   | row_local_priority_queue         | row_local_priority_queue_frequent_repartition   | Winner                                        |
|:-----------------------------|:-------|:---------------------------------|:---------------------------------|:---------------------------------|:-----------------------------------|:---------------------------------|:---------------------------------|:---------------------------------|:---------------------------------|:------------------------------|:---------------------------------|:------------------------------------------------|:----------------------------------------------|
| Value-Weighted Exposure      | lower  | 24124.580 [23798.140, 24451.020] | 24372.310 [24005.904, 24738.715] | 24020.356 [23629.565, 24411.147] | 24190.791 [23929.503, 24452.078]   | 24372.310 [24005.904, 24738.715] | 24372.310 [24005.904, 24738.715] | 24372.310 [24005.904, 24738.715] | 24271.973 [24039.277, 24504.669] | n/a                           | 24178.003 [24016.680, 24339.326] | 24410.061 [24268.259, 24551.862]                | s1_risk_open_core                             |
| Mean Response Time (s)       | lower  | 107.974 [100.385, 115.562]       | 86.635 [73.097, 100.172]         | 230.033 [180.262, 279.805]       | 106.404 [78.300, 134.509]          | 86.635 [73.097, 100.172]         | 86.635 [73.097, 100.172]         | 86.635 [73.097, 100.172]         | 81.719 [76.155, 87.282]          | n/a                           | 96.002 [86.524, 105.480]         | 68.513 [66.674, 70.353]                         | row_local_priority_queue_frequent_repartition |
| Last-Hour Birds Deterred (%) | higher | 0.397 [0.247, 0.547]             | 0.075 [0.008, 0.142]             | 0.887 [0.443, 1.331]             | 0.574 [0.271, 0.877]               | 0.075 [0.008, 0.142]             | 0.075 [0.008, 0.142]             | 0.075 [0.008, 0.142]             | 0.064 [0.029, 0.100]             | n/a                           | 0.158 [0.037, 0.278]             | 0.216 [0.139, 0.292]                            | s1_risk_open_core                             |
| Completed Tasks              | higher | 700.400 [587.565, 813.235]       | 288.000 [235.073, 340.927]       | 380.200 [296.241, 464.159]       | 308.600 [243.936, 373.264]         | 288.000 [235.073, 340.927]       | 288.000 [235.073, 340.927]       | 288.000 [235.073, 340.927]       | 287.400 [221.230, 353.570]       | 4892.000 [4830.658, 4953.342] | 1174.400 [1052.949, 1295.851]    | 1242.200 [1070.950, 1413.450]                   | main_native                                   |
| Completed Deterring          | higher | 64.400 [51.199, 77.601]          | 18.200 [11.600, 24.800]          | 92.400 [62.517, 122.283]         | 58.000 [38.726, 77.274]            | 18.200 [11.600, 24.800]          | 18.200 [11.600, 24.800]          | 18.200 [11.600, 24.800]          | 21.600 [19.314, 23.886]          | 4013.600 [4009.555, 4017.645] | 45.000 [37.693, 52.307]          | 49.400 [46.085, 52.715]                         | main_native                                   |
| Tasks / km Travel            | higher | 4.108 [3.333, 4.883]             | 1.413 [1.155, 1.672]             | 2.123 [1.533, 2.713]             | 2.350 [1.550, 3.151]               | 1.413 [1.155, 1.672]             | 1.413 [1.155, 1.672]             | 1.413 [1.155, 1.672]             | 1.588 [1.196, 1.980]             | 619.771 [589.844, 649.699]    | 7.275 [7.069, 7.480]             | 7.923 [7.470, 8.375]                            | main_native                                   |
| Boundary Message Count       | lower  | 138.000 [108.567, 167.433]       | 55.600 [40.448, 70.752]          | 55.600 [36.350, 74.850]          | 59.800 [40.512, 79.088]            | 55.600 [40.448, 70.752]          | 55.600 [40.448, 70.752]          | 55.600 [40.448, 70.752]          | 51.400 [44.077, 58.723]          | n/a                           | 71.400 [60.285, 82.515]          | 85.400 [74.337, 96.463]                         | s5_current_thesis_profile                     |

Positive advantage means the listed system outperformed `s1_risk_open_core` after accounting for metric direction.

## Advantage Vs Reference

| Metric                       | s0_simple_tasks_core vs s1_risk_open_core advantage %   | s1_main_core vs s1_risk_open_core advantage %   | s1_capacity_aware_selection_core vs s1_risk_open_core advantage %   | s2_direct_conflict vs s1_risk_open_core advantage %   | s3_persistence vs s1_risk_open_core advantage %   | s4_capacity_budget vs s1_risk_open_core advantage %   | s5_current_thesis_profile vs s1_risk_open_core advantage %   | main_native vs s1_risk_open_core advantage %   | row_local_priority_queue vs s1_risk_open_core advantage %   | row_local_priority_queue_frequent_repartition vs s1_risk_open_core advantage %   |
|:-----------------------------|:--------------------------------------------------------|:------------------------------------------------|:--------------------------------------------------------------------|:------------------------------------------------------|:--------------------------------------------------|:------------------------------------------------------|:-------------------------------------------------------------|:-----------------------------------------------|:------------------------------------------------------------|:---------------------------------------------------------------------------------|
| Value-Weighted Exposure      | -0.447 [-1.768, 0.874]                                  | -1.470 [-2.203, -0.738]                         | -0.740 [-2.829, 1.349]                                              | -1.470 [-2.203, -0.738]                               | -1.470 [-2.203, -0.738]                           | -1.470 [-2.203, -0.738]                               | -1.070 [-2.674, 0.534]                                       | n/a                                            | -0.676 [-1.948, 0.595]                                      | -1.647 [-3.211, -0.084]                                                          |
| Mean Response Time (s)       | 50.357 [38.212, 62.502]                                 | 59.655 [47.223, 72.086]                         | 52.902 [43.362, 62.442]                                             | 59.655 [47.223, 72.086]                               | 59.655 [47.223, 72.086]                           | 59.655 [47.223, 72.086]                               | 61.923 [49.926, 73.920]                                      | n/a                                            | 56.086 [45.799, 66.373]                                     | 68.448 [60.315, 76.580]                                                          |
| Last-Hour Birds Deterred (%) | -43.260 [-76.194, -10.327]                              | -89.764 [-98.613, -80.914]                      | 0.884 [-113.391, 115.158]                                           | -89.764 [-98.613, -80.914]                            | -89.764 [-98.613, -80.914]                        | -89.764 [-98.613, -80.914]                            | -88.342 [-100.125, -76.558]                                  | n/a                                            | -77.645 [-95.185, -60.106]                                  | -70.751 [-81.453, -60.048]                                                       |
| Completed Tasks              | 87.932 [67.735, 108.129]                                | -23.255 [-28.981, -17.529]                      | -18.066 [-25.267, -10.866]                                          | -23.255 [-28.981, -17.529]                            | -23.255 [-28.981, -17.529]                        | -23.255 [-28.981, -17.529]                            | -23.986 [-31.060, -16.913]                                   | 1267.413 [904.349, 1630.478]                   | 219.296 [172.757, 265.835]                                  | 244.803 [145.560, 344.046]                                                       |
| Completed Deterring          | -20.408 [-53.899, 13.083]                               | -78.777 [-86.416, -71.138]                      | -29.032 [-66.809, 8.744]                                            | -78.777 [-86.416, -71.138]                            | -78.777 [-86.416, -71.138]                        | -78.777 [-86.416, -71.138]                            | -73.296 [-83.811, -62.782]                                   | 4772.973 [3167.076, 6378.870]                  | -43.801 [-69.255, -18.347]                                  | -40.855 [-57.964, -23.747]                                                       |
| Tasks / km Travel            | 100.164 [72.299, 128.030]                               | -31.231 [-39.388, -23.074]                      | 10.057 [-4.424, 24.539]                                             | -31.231 [-39.388, -23.074]                            | -31.231 [-39.388, -23.074]                        | -31.231 [-39.388, -23.074]                            | -23.846 [-31.263, -16.429]                                   | 32068.600 [20849.627, 43287.573]               | 271.797 [167.338, 376.256]                                  | 306.110 [180.411, 431.808]                                                       |
| Boundary Message Count       | -167.806 [-243.611, -92.002]                            | -10.875 [-48.352, 26.601]                       | -25.244 [-80.885, 30.396]                                           | -10.875 [-48.352, 26.601]                             | -10.875 [-48.352, 26.601]                         | -10.875 [-48.352, 26.601]                             | -2.969 [-34.456, 28.518]                                     | n/a                                            | -39.917 [-76.488, -3.346]                                   | -79.305 [-157.444, -1.165]                                                       |

## Artifacts

- `per_run_metrics.csv`: one row per system per seed
- `per_run_timeseries.csv`: sampled trajectory metrics when available
- `summary_by_metric.csv`: aggregate means, CI95, and paired deltas vs the reference system
- `trajectory_compare.png`: generic backlog/completion trajectories
- `time_metric_compare.png`: time-series comparison for the selected result metrics
- `system_scoreboard.csv`: metric win counts on the selected scoreboard metric set
- `testbench_manifest.json`: resolved config and target metadata
- `report.md`: this summary
