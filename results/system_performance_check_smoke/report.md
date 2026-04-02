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
- `T_end`: `30.0`
- `W`: `500.0`
- `arrival_radius_m`: `3.0`
- `calibration_config_id`: ``
- `calibration_manifest_path`: ``
- `calibration_ranking_path`: ``
- `dt`: `10.0`
- `fps`: `1`
- `hold_time_s`: `20.0`
- `max_workers`: `1`
- `num_runs`: `1`
- `planner_profile`: ``
- `proposed_preventive_policy`: ``
- `sample_every_s`: `10.0`
- `seed_start`: `1000`
- `task_replan_period_s`: `45.0`
- `uav_fraction`: `0.0`
- `use_frozen_calibration`: `False`

## Metric Wins

| system          |   metric_wins |   win_share |
|:----------------|--------------:|------------:|
| main            |             5 |    0.833333 |
| reactive        |             1 |    0.166667 |
| prediction_only |             0 |    0        |
| proposed        |             0 |    0        |

## Summary

| Metric                      | proposed             | prediction_only      | main                       | reactive             | Winner   |
|:----------------------------|:---------------------|:---------------------|:---------------------------|:---------------------|:---------|
| Completed Tasks             | 0.000 [0.000, 0.000] | 0.000 [0.000, 0.000] | 6.000 [6.000, 6.000]       | 0.000 [0.000, 0.000] | main     |
| Completed Deterring         | 0.000 [0.000, 0.000] | 0.000 [0.000, 0.000] | 0.000 [0.000, 0.000]       | 0.000 [0.000, 0.000] | tie      |
| Completed Patrolling        | 0.000 [0.000, 0.000] | 0.000 [0.000, 0.000] | 6.000 [6.000, 6.000]       | 0.000 [0.000, 0.000] | main     |
| Completed Tasks / Hour      | 0.000 [0.000, 0.000] | 0.000 [0.000, 0.000] | 720.000 [720.000, 720.000] | 0.000 [0.000, 0.000] | main     |
| Mean Completion Latency (s) | n/a                  | n/a                  | 11.667 [11.667, 11.667]    | n/a                  | main     |
| Tasks / km Travel           | 0.000 [0.000, 0.000] | 0.000 [0.000, 0.000] | 40.173 [40.173, 40.173]    | n/a                  | main     |
| Mean Active Backlog         | 6.000 [6.000, 6.000] | 6.000 [6.000, 6.000] | 1.750 [1.750, 1.750]       | 0.000 [0.000, 0.000] | reactive |
| Final Active Backlog        | 6.000 [6.000, 6.000] | 6.000 [6.000, 6.000] | 0.000 [0.000, 0.000]       | 0.000 [0.000, 0.000] | tie      |

Positive advantage means the listed system outperformed `main` after accounting for metric direction.

## Advantage Vs Main

| Metric                      | proposed vs main advantage %   | prediction_only vs main advantage %   | reactive vs main advantage %   |
|:----------------------------|:-------------------------------|:--------------------------------------|:-------------------------------|
| Completed Tasks             | -100.000 [-100.000, -100.000]  | -100.000 [-100.000, -100.000]         | -100.000 [-100.000, -100.000]  |
| Completed Deterring         | n/a                            | n/a                                   | n/a                            |
| Completed Patrolling        | -100.000 [-100.000, -100.000]  | -100.000 [-100.000, -100.000]         | -100.000 [-100.000, -100.000]  |
| Completed Tasks / Hour      | -100.000 [-100.000, -100.000]  | -100.000 [-100.000, -100.000]         | -100.000 [-100.000, -100.000]  |
| Mean Completion Latency (s) | n/a                            | n/a                                   | n/a                            |
| Tasks / km Travel           | -100.000 [-100.000, -100.000]  | -100.000 [-100.000, -100.000]         | n/a                            |
| Mean Active Backlog         | -242.857 [-242.857, -242.857]  | -242.857 [-242.857, -242.857]         | 100.000 [100.000, 100.000]     |
| Final Active Backlog        | n/a                            | n/a                                   | n/a                            |

## Artifacts

- `per_run_metrics.csv`: one row per system per seed
- `summary_by_metric.csv`: aggregate means, CI95, and paired deltas vs main
- `system_scoreboard.csv`: metric win counts by system
- `per_run_timeseries.csv`: sampled trajectory metrics when available
- `summary_compare.png`: grouped aggregate metric plot
- `trajectory_compare.png`: mean trajectories over time when timeseries are available
