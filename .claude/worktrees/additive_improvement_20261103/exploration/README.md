# Exploration Variants

This folder is an isolated sandbox for planner experiments that are intentionally more aggressive than the thesis-facing runtime.

Current variants:

1. `row_local_priority_queue`
   Uses whole-row ownership, live-pose row repartitioning, and per-robot local priority queues instead of the normal assignment stage.
2. `row_local_priority_queue_frequent_repartition`
   Same row/local queue idea, but zones are recomputed more often and task selection biases more strongly toward nearby tasks.

These variants are exploratory only. They are not wired into the main thesis runners.

## Implemented Math

The exploration line keeps the same truth process, SESTPP update, and task-scoring math as the main runtime, but changes partitioning and task choice.

### Whole-Row Partitioning

Instead of polygonal zones that can split partial rows, each vineyard row center `y_k` is assigned to robot `r` by minimizing:

```text
score_row(k, r) =
    (y_k - anchor_y_r)^2
    - (row_health_gain_m * normalized_weight_r)^2
```

This produces contiguous full-row ownership blocks. The live robot pose can be used to refresh `anchor_y_r`, so repartitioning follows robot motion.

### Local Priority Queue

Global assignment is replaced by per-robot local task ordering. For a candidate task and robot:

```text
priority =
    task_value
  + task_type_bonus
  + zone_bonus
  + 0.25 * support
  + 0.50 * selection_weight
  - local_queue_distance_weight * distance_to_robot
  - local_queue_age_weight * task_age
```

Queue replacement only happens when the incoming task beats the worst replaceable queued task by `local_queue_preempt_margin`.

### Frequent-Repartition Variant

`row_local_priority_queue_frequent_repartition` keeps the same queue formula but:

- recomputes row ownership more often
- updates row anchors from robot pose aggressively
- penalizes distance more strongly, so near tasks are favored earlier

## Run

List variants:

```powershell
python -m exploration.run_variant --list
```

Run the base exploration variant:

```powershell
python -m exploration.run_variant --variant row_local_priority_queue --num-runs 1 --t-end 1800
```

Run both exploratory variants:

```powershell
python -m exploration.run_variant --variant row_local_priority_queue --variant row_local_priority_queue_frequent_repartition --num-runs 3 --t-end 3600
```

Outputs are written under `results/exploration/<variant>/`.

## Calibrate Local Queue Weights

Run a risk-open calibration sweep for the exploratory local queue. Every sweep variant forces:

```text
model_deterring_risk_threshold = 0.0
model_deterring_risk_scale = 1e-4
```

so the preventive branch is open before queue weights are tuned.

Example:

```powershell
python -m exploration.local_queue_weight_sweep --base-variant row_local_priority_queue --num-runs 3 --t-end 3600 --max-workers 4
```

This writes:

- `results/exploration/local_queue_weight_sweep/local_queue_weight_runtime.csv`
- `results/exploration/local_queue_weight_sweep/local_queue_weight_summary.csv`
- `results/exploration/local_queue_weight_sweep/local_queue_weight_long.csv`
- `results/exploration/local_queue_weight_sweep/local_queue_weight_sweep.md`
- `results/exploration/local_queue_weight_sweep/local_queue_weight_sweep_manifest.json`

The sweep changes one parameter family at a time around the base exploration variant:

- `local_queue_distance_weight`
- `local_queue_deterring_bonus`
- `local_queue_direct_detection_bonus`
- `local_queue_age_weight`
- `local_queue_preempt_margin`
- `zone_repartition_period_s`

## Compare Seeding Phase

The simulator already supports a pre-run seeding / warmup phase through `warmup_s`. During this phase, the ground-truth process burns in to seed SESTPP state, then the public metrics are reset before the scored run begins.

Run a matched-seed warmup sweep across selected simplification stages and exploration variants:

```powershell
python -m exploration.seeding_phase_compare --stage s1_risk_open_core --variant row_local_priority_queue --warmup-values 0,300,900,1800 --num-runs 3 --t-end 3600 --max-workers 4
```

Outputs are written under `results/seeding_phase_compare/`:

- `seeding_phase_summary.csv`
- `seeding_phase_best_by_system.csv`
- `seeding_phase_runtime.csv`
- `seeding_phase_report.md`
- `seeding_phase_manifest.json`

## Compare Against Existing Systems

Run the exploration variants against the default simplification / thesis comparison set:

```powershell
python -m exploration.compare_system_performance --num-runs 3 --t-end 3600 --max-workers 4
```

Outputs are written under `results/exploration_compare/`, including:

- `system_comparison_summary.csv`
- `system_comparison.md`
- `system_comparison_manifest.json`
- `system_comparison_runtime.csv`
