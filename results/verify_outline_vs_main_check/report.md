# Outline Vs Main Check

This benchmark compares the sibling `main` worktree against a current-workspace runtime that keeps only the thesis-outline additions.

## Repositories

- current: `C:\Users\gabri\Documents\CalPoly\Thesis\Code`
- current branch: `snapshot/intervention-refactor-planner-diagnostics-20260401`
- current commit: `cbfbfc898d83455806d72d9341830357a1e699c3`
- current dirty: `True`
- main: `C:\Users\gabri\Documents\CalPoly\Thesis\Code-main`
- main branch: `main`
- main commit: `950adbabb055cc1e470c44efb3e0a165f16f3904`
- main dirty: `False`

## Outline Stage

- key: `s1_risk_open_core`
- title: `Main Core With Risk Gate Open`
- module: `DeterrentSystem`
- description: Same stripped-down main runtime as stage 1, but with the heuristic preventive risk threshold fixed at 0.0 so the model-scored preventive branch is active and can be debugged before later protection layers are added back.
- added_back: `Keep the main runtime core., Force the heuristic preventive risk gate open (threshold 0.0, scale 1e-4).`

## Systems

- `outline_only`: Current workspace constrained to the thesis-outline-only additions: main runtime plus the stripped-down core stage overrides, with later protective and throttling heuristics removed.
- `main`: Sibling main worktree benchmarked with its native supported defaults.

## Benchmark Parameters

- `H`: `500.0`
- `NX`: `80`
- `NY`: `64`
- `Nrobots`: `6`
- `T_end`: `60.0`
- `W`: `500.0`
- `arrival_radius_m`: `3.0`
- `dt`: `5.0`
- `fps`: `1`
- `hold_time_s`: `20.0`
- `max_workers`: `1`
- `num_runs`: `1`
- `outline_stage`: `s1_risk_open_core`
- `sample_every_s`: `30.0`
- `seed_start`: `1000`
- `task_replan_period_s`: `45.0`
- `uav_fraction`: `0.0`

## Common Metric Wins

| system       |   metric_wins |   win_share |
|:-------------|--------------:|------------:|
| main         |             5 |    0.714286 |
| outline_only |             2 |    0.285714 |

## Common Summary

| Metric                      | outline_only         | main                       | Winner       |
|:----------------------------|:---------------------|:---------------------------|:-------------|
| Completed Tasks             | 0.000 [0.000, 0.000] | 6.000 [6.000, 6.000]       | main         |
| Completed Deterring         | 0.000 [0.000, 0.000] | 0.000 [0.000, 0.000]       | tie          |
| Completed Patrolling        | 0.000 [0.000, 0.000] | 6.000 [6.000, 6.000]       | main         |
| Completed Tasks / Hour      | 0.000 [0.000, 0.000] | 360.000 [360.000, 360.000] | main         |
| Mean Completion Latency (s) | n/a                  | 15.000 [15.000, 15.000]    | main         |
| Tasks / km Travel           | 0.000 [0.000, 0.000] | 18.366 [18.366, 18.366]    | main         |
| Mean Active Backlog         | 5.077 [5.077, 5.077] | 5.692 [5.692, 5.692]       | outline_only |
| Final Active Backlog        | 3.000 [3.000, 3.000] | 14.000 [14.000, 14.000]    | outline_only |

Positive advantage means `outline_only` outperformed `main` after accounting for metric direction.

## Common Advantage Vs Main

| Metric                      | outline_only vs main advantage %   |
|:----------------------------|:-----------------------------------|
| Completed Tasks             | -100.000 [-100.000, -100.000]      |
| Completed Deterring         | n/a                                |
| Completed Patrolling        | -100.000 [-100.000, -100.000]      |
| Completed Tasks / Hour      | -100.000 [-100.000, -100.000]      |
| Mean Completion Latency (s) | n/a                                |
| Tasks / km Travel           | -100.000 [-100.000, -100.000]      |
| Mean Active Backlog         | 10.811 [10.811, 10.811]            |
| Final Active Backlog        | 78.571 [78.571, 78.571]            |

## Native Metric Summary

Rows marked `n/a` for `main` indicate that the sibling main worktree does not emit that metric in this harness.

| Metric                              | outline_only            | main   | Winner   |
|:------------------------------------|:------------------------|:-------|:---------|
| Native Value-Weighted Exposure      | 92.352 [92.352, 92.352] | n/a    |          |
| Native Mean Response Time (s)       | n/a                     | n/a    |          |
| Native Last-Hour Birds Deterred (%) | 0.000 [0.000, 0.000]    | n/a    |          |
| Native Birds Deterred (%)           | 0.000 [0.000, 0.000]    | n/a    |          |
| Native Boundary Message Count       | 0.000 [0.000, 0.000]    | n/a    |          |

## Artifacts

- `per_run_metrics.csv`: one row per system per seed
- `summary_common.csv`: aggregate common metrics used for fair cross-worktree comparison
- `summary_native.csv`: native current-workspace metrics when emitted by the runner
- `system_scoreboard.csv`: metric win counts on the common comparison set
- `per_run_timeseries.csv`: sampled trajectory metrics when available
- `summary_compare.png`: grouped common-metric plot
