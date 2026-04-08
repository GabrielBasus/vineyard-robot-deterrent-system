# Cross-System Performance Comparison

Systems were run on matched seeds and summarized using the proposed baseline plus its paired gains over `prediction_only` and `reactive`.

## Highlights

- Best exposure: `row_local_priority_queue` at `2.62` with `0.00%` vs reactive.
- Best bird-deterrence: `row_local_priority_queue` at `0.00%`.
- Best balanced rank: `row_local_priority_queue` with overall rank `1.00`.

## Systems

### row_local_priority_queue: Row-Block Local Priority Queue
- Exposure: `2.62` (vs prediction `0.00%`, vs reactive `0.00%`).
- Response time: `nan s` (vs reactive `nan%`).
- Bird deterrence: `0.00%` (delta vs reactive `0.00` pts).
- Communication: `0.00` via `boundary_bytes_sent_mean`.
- Preventive completions / planner rejections: `0.00` / `0.00`.

### s0_simple_tasks_core: Simple Tasks Core
- Exposure: `2.62` (vs prediction `0.00%`, vs reactive `0.00%`).
- Response time: `nan s` (vs reactive `nan%`).
- Bird deterrence: `0.00%` (delta vs reactive `0.00` pts).
- Communication: `0.00` via `boundary_bytes_sent_mean`.
- Preventive completions / planner rejections: `0.00` / `4.00`.

## Manifest

- `s0_simple_tasks_core`: kind=`simplification_stage` output=`results\exploration_compare_postfix\s0_simple_tasks_core`
- `row_local_priority_queue`: kind=`exploration_variant` output=`results\exploration_compare_postfix\row_local_priority_queue`
