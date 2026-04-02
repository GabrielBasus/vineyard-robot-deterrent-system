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
| Completed Tasks             | 81.000 [67.520, 94.480] | 1128.200 [1102.891, 1153.509] | -92.829 [-93.949, -91.708] | main     |
| Completed Deterring         | 58.600 [44.788, 72.412] | 693.200 [675.687, 710.713]    | -91.564 [-93.489, -89.640] | main     |
| Completed Patrolling        | 22.400 [13.643, 31.157] | 435.000 [417.656, 452.344]    | -94.923 [-96.788, -93.058] | main     |
| Completed Tasks / Hour      | 81.000 [67.520, 94.480] | 1128.200 [1102.891, 1153.509] | -92.829 [-93.949, -91.708] | main     |
| Mean Completion Latency (s) | 75.542 [66.022, 85.062] | 178.672 [148.381, 208.964]    | 56.614 [48.152, 65.076]    | current  |
| Tasks / km Travel           | 1.748 [1.422, 2.075]    | 95.242 [83.574, 106.910]      | -98.146 [-98.478, -97.813] | main     |
| Mean Active Backlog         | 7.360 [7.056, 7.663]    | 83.447 [68.554, 98.340]       | 90.872 [89.206, 92.538]    | current  |
| Final Active Backlog        | 7.000 [5.614, 8.386]    | 146.600 [117.386, 175.814]    | 94.974 [93.527, 96.420]    | current  |

Positive advantage means the current workspace outperformed main after accounting for metric direction.

## Artifacts

- `per_run_metrics.csv`: one row per system per seed
- `summary_by_metric.csv`: aggregate metrics with CI95 and paired seed deltas
- `per_run_timeseries.csv`: sampled trajectory metrics
- `summary_compare.png`: bar chart of aggregate outcomes
- `trajectory_compare.png`: mean trajectories over time when timeseries are available
