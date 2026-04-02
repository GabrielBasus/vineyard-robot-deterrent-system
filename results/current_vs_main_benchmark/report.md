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
- `T_end`: `3600.0`
- `W`: `500.0`
- `arrival_radius_m`: `3.0`
- `current_simulation_mode`: `proposed`
- `dt`: `5.0`
- `fps`: `1`
- `hold_time_s`: `20.0`
- `num_runs`: `5`
- `sample_every_s`: `60.0`
- `seed_start`: `1000`
- `task_replan_period_s`: `45.0`
- `uav_fraction`: `0.0`

## Summary

| Metric                      | current                 | main                          | current Advantage %        | Winner   |
|:----------------------------|:------------------------|:------------------------------|:---------------------------|:---------|
| Completed Tasks             | 81.000 [67.520, 94.480] | 1127.600 [1114.154, 1141.046] | -92.819 [-93.984, -91.655] | main     |
| Completed Deterring         | 58.600 [44.788, 72.412] | 691.200 [675.021, 707.379]    | -91.533 [-93.491, -89.576] | main     |
| Completed Patrolling        | 22.400 [13.643, 31.157] | 436.400 [429.051, 443.749]    | -94.896 [-96.832, -92.960] | main     |
| Completed Tasks / Hour      | 81.000 [67.520, 94.480] | 1127.600 [1114.154, 1141.046] | -92.819 [-93.984, -91.655] | main     |
| Mean Completion Latency (s) | 75.542 [66.022, 85.062] | 179.600 [157.342, 201.858]    | 57.665 [52.958, 62.371]    | current  |
| Tasks / km Travel           | 1.748 [1.422, 2.075]    | 92.666 [82.612, 102.721]      | -98.096 [-98.450, -97.742] | main     |
| Mean Active Backlog         | 7.360 [7.056, 7.663]    | 81.897 [66.687, 97.106]       | 90.666 [88.862, 92.469]    | current  |
| Final Active Backlog        | 7.000 [5.614, 8.386]    | 147.200 [120.748, 173.652]    | 95.071 [93.880, 96.262]    | current  |

Positive advantage means the current workspace outperformed main after accounting for metric direction.

## Artifacts

- `per_run_metrics.csv`: one row per system per seed
- `summary_by_metric.csv`: aggregate metrics with CI95 and paired seed deltas
- `per_run_timeseries.csv`: sampled trajectory metrics
- `summary_compare.png`: bar chart of aggregate outcomes
- `trajectory_compare.png`: mean trajectories over time when timeseries are available
