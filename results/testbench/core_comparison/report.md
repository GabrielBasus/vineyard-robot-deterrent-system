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
| main_native                                   |             1 |        0.25 |
| row_local_priority_queue_frequent_repartition |             1 |        0.25 |
| s1_capacity_aware_selection_core              |             1 |        0.25 |
| s1_risk_open_core                             |             1 |        0.25 |
| row_local_priority_queue                      |             0 |        0    |
| s0_simple_tasks_core                          |             0 |        0    |
| s1_main_core                                  |             0 |        0    |
| s2_direct_conflict                            |             0 |        0    |
| s3_persistence                                |             0 |        0    |
| s4_capacity_budget                            |             0 |        0    |
| s5_current_thesis_profile                     |             0 |        0    |

## Metric Summary

| Metric                       | Goal   | s0_simple_tasks_core          | s1_main_core                  | s1_risk_open_core             | s1_capacity_aware_selection_core   | s2_direct_conflict            | s3_persistence                | s4_capacity_budget            | s5_current_thesis_profile     | main_native                   | row_local_priority_queue      | row_local_priority_queue_frequent_repartition   | Winner                                        |
|:-----------------------------|:-------|:------------------------------|:------------------------------|:------------------------------|:-----------------------------------|:------------------------------|:------------------------------|:------------------------------|:------------------------------|:------------------------------|:------------------------------|:------------------------------------------------|:----------------------------------------------|
| Value-Weighted Exposure      | lower  | 5544.479 [5284.654, 5804.304] | 5675.508 [5339.250, 6011.766] | 5518.265 [5224.742, 5811.787] | 5499.599 [5191.916, 5807.282]      | 5675.508 [5339.250, 6011.766] | 5675.508 [5339.250, 6011.766] | 5675.508 [5339.250, 6011.766] | 5672.486 [5508.326, 5836.647] | n/a                           | 5600.134 [5439.822, 5760.446] | 5679.046 [5411.175, 5946.916]                   | s1_capacity_aware_selection_core              |
| Mean Response Time (s)       | lower  | 120.291 [100.999, 139.582]    | 74.807 [61.744, 87.870]       | 128.843 [33.087, 224.600]     | 98.535 [34.655, 162.415]           | 74.807 [61.744, 87.870]       | 74.807 [61.744, 87.870]       | 74.807 [61.744, 87.870]       | 81.984 [70.894, 93.073]       | n/a                           | 75.150 [64.064, 86.236]       | 61.543 [58.399, 64.687]                         | row_local_priority_queue_frequent_repartition |
| Last-Hour Birds Deterred (%) | higher | 0.219 [0.092, 0.346]          | 0.051 [0.029, 0.073]          | 0.686 [0.533, 0.838]          | 0.328 [0.285, 0.372]               | 0.051 [0.029, 0.073]          | 0.051 [0.029, 0.073]          | 0.051 [0.029, 0.073]          | 0.154 [0.111, 0.196]          | n/a                           | 0.143 [0.077, 0.210]          | 0.117 [-0.001, 0.235]                           | s1_risk_open_core                             |
| Completed Tasks              | higher | 262.667 [238.760, 286.574]    | 83.000 [57.420, 108.580]      | 96.667 [36.040, 157.293]      | 67.000 [31.811, 102.189]           | 83.000 [57.420, 108.580]      | 83.000 [57.420, 108.580]      | 83.000 [57.420, 108.580]      | 80.667 [69.793, 91.540]       | 1193.333 [1182.460, 1204.207] | 279.000 [270.457, 287.543]    | 319.000 [268.027, 369.973]                      | main_native                                   |
| Completed Deterring          | higher | 16.000 [9.210, 22.790]        | 6.667 [3.029, 10.304]         | 21.667 [18.819, 24.514]       | 13.000 [8.920, 17.080]             | 6.667 [3.029, 10.304]         | 6.667 [3.029, 10.304]         | 6.667 [3.029, 10.304]         | 7.667 [5.938, 9.395]          | 985.000 [983.868, 986.132]    | 8.000 [3.920, 12.080]         | 11.667 [9.938, 13.395]                          | main_native                                   |
| Tasks / km Travel            | higher | 6.684 [5.892, 7.476]          | 1.656 [1.122, 2.189]          | 2.283 [0.487, 4.079]          | 2.162 [0.665, 3.660]               | 1.656 [1.122, 2.189]          | 1.656 [1.122, 2.189]          | 1.656 [1.122, 2.189]          | 1.769 [1.479, 2.060]          | 332.517 [324.577, 340.457]    | 6.053 [5.662, 6.444]          | 7.259 [6.230, 8.289]                            | main_native                                   |
| Boundary Message Count       | lower  | 35.333 [24.169, 46.497]       | 14.667 [1.405, 27.928]        | 18.000 [14.080, 21.920]       | 28.667 [3.431, 53.903]             | 14.667 [1.405, 27.928]        | 14.667 [1.405, 27.928]        | 14.667 [1.405, 27.928]        | 18.667 [5.025, 32.309]        | n/a                           | 16.333 [6.709, 25.958]        | 18.667 [15.210, 22.124]                         | tie                                           |

Positive advantage means the listed system outperformed `s1_risk_open_core` after accounting for metric direction.

## Advantage Vs Reference

| Metric                       | s0_simple_tasks_core vs s1_risk_open_core advantage %   | s1_main_core vs s1_risk_open_core advantage %   | s1_capacity_aware_selection_core vs s1_risk_open_core advantage %   | s2_direct_conflict vs s1_risk_open_core advantage %   | s3_persistence vs s1_risk_open_core advantage %   | s4_capacity_budget vs s1_risk_open_core advantage %   | s5_current_thesis_profile vs s1_risk_open_core advantage %   | main_native vs s1_risk_open_core advantage %   | row_local_priority_queue vs s1_risk_open_core advantage %   | row_local_priority_queue_frequent_repartition vs s1_risk_open_core advantage %   |
|:-----------------------------|:--------------------------------------------------------|:------------------------------------------------|:--------------------------------------------------------------------|:------------------------------------------------------|:--------------------------------------------------|:------------------------------------------------------|:-------------------------------------------------------------|:-----------------------------------------------|:------------------------------------------------------------|:---------------------------------------------------------------------------------|
| Value-Weighted Exposure      | -0.517 [-3.743, 2.710]                                  | -2.834 [-3.779, -1.889]                         | 0.345 [-0.271, 0.960]                                               | -2.834 [-3.779, -1.889]                               | -2.834 [-3.779, -1.889]                           | -2.834 [-3.779, -1.889]                               | -2.869 [-5.786, 0.048]                                       | n/a                                            | -1.551 [-4.002, 0.899]                                      | -2.951 [-5.979, 0.077]                                                           |
| Mean Response Time (s)       | -17.698 [-81.770, 46.374]                               | 29.329 [-5.246, 63.904]                         | 19.640 [-2.276, 41.556]                                             | 29.329 [-5.246, 63.904]                               | 29.329 [-5.246, 63.904]                           | 29.329 [-5.246, 63.904]                               | 17.368 [-31.763, 66.499]                                     | n/a                                            | 23.814 [-26.585, 74.212]                                    | 40.092 [8.431, 71.754]                                                           |
| Last-Hour Birds Deterred (%) | -64.657 [-93.875, -35.439]                              | -91.916 [-97.582, -86.250]                      | -50.395 [-65.881, -34.909]                                          | -91.916 [-97.582, -86.250]                            | -91.916 [-97.582, -86.250]                        | -91.916 [-97.582, -86.250]                            | -76.274 [-88.333, -64.215]                                   | n/a                                            | -78.236 [-89.544, -66.929]                                  | -84.660 [-100.088, -69.232]                                                      |
| Completed Tasks              | 216.620 [75.675, 357.566]                               | -5.709 [-32.231, 20.812]                        | -28.696 [-39.588, -17.803]                                          | -5.709 [-32.231, 20.812]                              | -5.709 [-32.231, 20.812]                          | -5.709 [-32.231, 20.812]                              | -3.292 [-46.506, 39.922]                                     | 1369.330 [641.741, 2096.918]                   | 245.496 [69.975, 421.018]                                   | 289.264 [81.991, 496.537]                                                        |
| Completed Deterring          | -27.658 [-49.748, -5.569]                               | -70.116 [-83.944, -56.288]                      | -40.663 [-51.982, -29.345]                                          | -70.116 [-83.944, -56.288]                            | -70.116 [-83.944, -56.288]                        | -70.116 [-83.944, -56.288]                            | -64.726 [-70.337, -59.115]                                   | 4488.184 [3872.753, 5103.616]                  | -63.816 [-80.245, -47.387]                                  | -45.362 [-58.280, -32.443]                                                       |
| Tasks / km Travel            | 272.077 [69.783, 474.372]                               | -14.138 [-47.312, 19.036]                       | -2.199 [-14.235, 9.836]                                             | -14.138 [-47.312, 19.036]                             | -14.138 [-47.312, 19.036]                         | -14.138 [-47.312, 19.036]                             | -2.319 [-55.337, 50.699]                                     | 18898.479 [7786.065, 30010.893]                | 247.155 [46.293, 448.018]                                   | 304.180 [77.812, 530.548]                                                        |
| Boundary Message Count       | -98.106 [-163.730, -32.482]                             | 24.242 [-28.187, 76.671]                        | -48.485 [-147.637, 50.667]                                          | 24.242 [-28.187, 76.671]                              | 24.242 [-28.187, 76.671]                          | 24.242 [-28.187, 76.671]                              | -5.303 [-91.338, 80.732]                                     | n/a                                            | 3.598 [-64.270, 71.467]                                     | -7.576 [-44.541, 29.389]                                                         |

## Artifacts

- `per_run_metrics.csv`: one row per system per seed
- `per_run_timeseries.csv`: sampled trajectory metrics when available
- `summary_by_metric.csv`: aggregate means, CI95, and paired deltas vs the reference system
- `trajectory_compare.png`: generic backlog/completion trajectories
- `time_metric_compare.png`: time-series comparison for the selected result metrics
- `system_scoreboard.csv`: metric win counts on the selected scoreboard metric set
- `testbench_manifest.json`: resolved config and target metadata
- `report.md`: this summary
