# Current vs Main Benchmark

## Repositories

- `current`: `C:\Users\gabri\Documents\CalPoly\Thesis\Code`
- branch: `share-for-ai-20260330`
- commit: `c74a62945105fb655edc4fb94a1951b480dbb9a6`
- dirty: `True`
- `main`: `C:\Users\gabri\Documents\CalPoly\Thesis\Code-main`
- branch: `main`
- commit: `950adbabb055cc1e470c44efb3e0a165f16f3904`
- dirty: `False`

## Benchmark Parameters

- `H`: `500.0`
- `NX`: `80`
- `NY`: `64`
- `Nrobots`: `6`
- `T_end`: `60.0`
- `W`: `500.0`
- `arrival_radius_m`: `3.0`
- `current_simulation_mode`: `proposed`
- `dt`: `5.0`
- `fps`: `1`
- `hold_time_s`: `20.0`
- `num_runs`: `1`
- `sample_every_s`: `15.0`
- `seed_start`: `1000`
- `task_replan_period_s`: `45.0`
- `uav_fraction`: `0.0`

## Summary

| Metric                      | current              | main                       | current Advantage %           | Winner   |
|:----------------------------|:---------------------|:---------------------------|:------------------------------|:---------|
| Completed Tasks             | 0.000 [0.000, 0.000] | 6.000 [6.000, 6.000]       | -100.000 [-100.000, -100.000] | main     |
| Completed Deterring         | 0.000 [0.000, 0.000] | 0.000 [0.000, 0.000]       | n/a                           | tie      |
| Completed Patrolling        | 0.000 [0.000, 0.000] | 6.000 [6.000, 6.000]       | -100.000 [-100.000, -100.000] | main     |
| Completed Tasks / Hour      | 0.000 [0.000, 0.000] | 360.000 [360.000, 360.000] | -100.000 [-100.000, -100.000] | main     |
| Mean Completion Latency (s) | n/a                  | 15.000 [15.000, 15.000]    | n/a                           | main     |
| Tasks / km Travel           | 0.000 [0.000, 0.000] | 18.366 [18.366, 18.366]    | -100.000 [-100.000, -100.000] | main     |
| Mean Active Backlog         | 6.923 [6.923, 6.923] | 5.692 [5.692, 5.692]       | -21.622 [-21.622, -21.622]    | main     |
| Final Active Backlog        | 9.000 [9.000, 9.000] | 14.000 [14.000, 14.000]    | 35.714 [35.714, 35.714]       | current  |

Positive advantage means the current workspace outperformed main after accounting for metric direction.

## Artifacts

- `per_run_metrics.csv`: one row per system per seed
- `summary_by_metric.csv`: aggregate metrics with CI95 and paired seed deltas
- `per_run_timeseries.csv`: sampled trajectory metrics
- `summary_compare.png`: bar chart of aggregate outcomes
- `trajectory_compare.png`: mean trajectories over time when timeseries are available
