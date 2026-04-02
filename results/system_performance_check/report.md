# System Performance Check

## Repositories

- current: `C:\Users\gabri\Documents\CalPoly\Thesis\Code`
- current branch: `share-for-ai-20260330`
- current commit: `c74a62945105fb655edc4fb94a1951b480dbb9a6`
- current dirty: `True`
- main: `C:\Users\gabri\Documents\CalPoly\Thesis\Code-main`
- main branch: `main`
- main commit: `950adbabb055cc1e470c44efb3e0a165f16f3904`
- main dirty: `False`

## Systems

- `proposed`: Current workspace with predictive patrol, intervention feedback, and model-scored preventive deterring enabled.
- `prediction_only`: Current workspace with predictive patrol enabled, but without intervention feedback or model-scored preventive deterring.
- `main`: Sibling main worktree benchmarked with its native supported defaults.
- `reactive`: Current workspace in detections-only mode with no predictive patrol, no intervention feedback, and no model-scored preventive deterring.

## Benchmark Parameters

- `H`: `500.0`
- `NX`: `80`
- `NY`: `64`
- `Nrobots`: `6`
- `T_end`: `3600.0`
- `W`: `500.0`
- `arrival_radius_m`: `3.0`
- `calibration_config_id`: ``
- `calibration_manifest_path`: ``
- `calibration_ranking_path`: ``
- `dt`: `5.0`
- `fps`: `1`
- `hold_time_s`: `20.0`
- `max_workers`: `1`
- `num_runs`: `5`
- `planner_profile`: ``
- `proposed_preventive_policy`: ``
- `sample_every_s`: `60.0`
- `seed_start`: `1000`
- `task_replan_period_s`: `45.0`
- `uav_fraction`: `0.0`
- `use_frozen_calibration`: `False`

## Metric Wins

| system          |   metric_wins |   win_share |
|:----------------|--------------:|------------:|
| main            |             5 |    0.714286 |
| reactive        |             2 |    0.285714 |
| prediction_only |             0 |    0        |
| proposed        |             0 |    0        |

## Summary

| Metric                      | proposed                | prediction_only         | main                          | reactive                 | Winner   |
|:----------------------------|:------------------------|:------------------------|:------------------------------|:-------------------------|:---------|
| Completed Tasks             | 31.600 [24.517, 38.683] | 31.600 [24.517, 38.683] | 1127.200 [1107.704, 1146.696] | 9.400 [6.085, 12.715]    | main     |
| Completed Deterring         | 5.400 [4.401, 6.399]    | 5.400 [4.401, 6.399]    | 689.800 [674.651, 704.949]    | 9.400 [6.085, 12.715]    | main     |
| Completed Patrolling        | 26.200 [18.908, 33.492] | 26.200 [18.908, 33.492] | 437.400 [421.006, 453.794]    | 0.000 [0.000, 0.000]     | main     |
| Completed Tasks / Hour      | 31.600 [24.517, 38.683] | 31.600 [24.517, 38.683] | 1127.200 [1107.704, 1146.696] | 9.400 [6.085, 12.715]    | main     |
| Mean Completion Latency (s) | 37.178 [30.588, 43.768] | 37.178 [30.588, 43.768] | 169.292 [150.575, 188.009]    | 99.077 [80.275, 117.878] | tie      |
| Tasks / km Travel           | 0.650 [0.500, 0.801]    | 0.650 [0.500, 0.801]    | 92.769 [85.041, 100.497]      | 2.751 [1.765, 3.738]     | main     |
| Mean Active Backlog         | 5.969 [5.903, 6.035]    | 5.969 [5.903, 6.035]    | 82.050 [67.250, 96.849]       | 0.422 [0.355, 0.489]     | reactive |
| Final Active Backlog        | 6.400 [5.920, 6.880]    | 6.400 [5.920, 6.880]    | 147.000 [113.640, 180.360]    | 0.000 [0.000, 0.000]     | reactive |

Positive advantage means the listed system outperformed `main` after accounting for metric direction.

## Advantage Vs Main

| Metric                      | proposed vs main advantage %   | prediction_only vs main advantage %   | reactive vs main advantage %   |
|:----------------------------|:-------------------------------|:--------------------------------------|:-------------------------------|
| Completed Tasks             | -97.200 [-97.812, -96.589]     | -97.200 [-97.812, -96.589]            | -99.167 [-99.457, -98.877]     |
| Completed Deterring         | -99.217 [-99.363, -99.071]     | -99.217 [-99.363, -99.071]            | -98.636 [-99.118, -98.154]     |
| Completed Patrolling        | -93.987 [-95.732, -92.242]     | -93.987 [-95.732, -92.242]            | -100.000 [-100.000, -100.000]  |
| Completed Tasks / Hour      | -97.200 [-97.812, -96.589]     | -97.200 [-97.812, -96.589]            | -99.167 [-99.457, -98.877]     |
| Mean Completion Latency (s) | 77.682 [72.616, 82.747]        | 77.682 [72.616, 82.747]               | 41.194 [31.255, 51.133]        |
| Tasks / km Travel           | -99.299 [-99.446, -99.153]     | -99.299 [-99.446, -99.153]            | -97.007 [-98.156, -95.858]     |
| Mean Active Backlog         | 92.435 [90.854, 94.016]        | 92.435 [90.854, 94.016]               | 99.463 [99.324, 99.602]        |
| Final Active Backlog        | 95.412 [94.338, 96.485]        | 95.412 [94.338, 96.485]               | 100.000 [100.000, 100.000]     |

## Artifacts

- `per_run_metrics.csv`: one row per system per seed
- `summary_by_metric.csv`: aggregate means, CI95, and paired deltas vs main
- `system_scoreboard.csv`: metric win counts by system
- `per_run_timeseries.csv`: sampled trajectory metrics when available
- `summary_compare.png`: grouped aggregate metric plot
- `trajectory_compare.png`: mean trajectories over time when timeseries are available
