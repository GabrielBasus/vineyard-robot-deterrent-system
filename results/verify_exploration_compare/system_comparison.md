# Cross-System Performance Comparison

Systems were run on matched seeds and summarized using the proposed baseline plus its paired gains over `prediction_only` and `reactive`.

## Highlights

- Best exposure: `s0_simple_tasks_core` at `5.58` with `0.00%` vs reactive.
- Best bird-deterrence: `s0_simple_tasks_core` at `0.00%`.
- Best balanced rank: `s0_simple_tasks_core` with overall rank `1.25`.

## Systems

### s0_simple_tasks_core: Simple Tasks Core
- Exposure: `5.58` (vs prediction `0.00%`, vs reactive `0.00%`).
- Response time: `nan s` (vs reactive `nan%`).
- Bird deterrence: `0.00%` (delta vs reactive `0.00` pts).
- Communication: `0.00` via `boundary_bytes_sent_mean`.
- Preventive completions / planner rejections: `0.00` / `2.00`.

### row_local_priority_queue: Row-Block Local Priority Queue
- Exposure: `5.58` (vs prediction `0.00%`, vs reactive `0.00%`).
- Response time: `nan s` (vs reactive `nan%`).
- Bird deterrence: `0.00%` (delta vs reactive `0.00` pts).
- Communication: `128.00` via `boundary_bytes_sent_mean`.
- Preventive completions / planner rejections: `0.00` / `0.00`.

## Manifest

- `s0_simple_tasks_core`: kind=`simplification_stage` output=`results\verify_exploration_compare\s0_simple_tasks_core`
- `row_local_priority_queue`: kind=`exploration_variant` output=`results\verify_exploration_compare\row_local_priority_queue`
