# Cross-System Performance Comparison

Systems were run on matched seeds and summarized using the proposed baseline plus its paired gains over `prediction_only` and `reactive`.

## Highlights

- Best exposure: `s1_risk_open_core` at `5.58` with `0.00%` vs reactive.
- Best last-hour bird deterrence: `s1_risk_open_core` at `0.00%`.
- Best balanced rank: `s1_risk_open_core` with overall rank `1.25`.

## Systems

### s1_risk_open_core: Main Core With Risk Gate Open
- Exposure: `5.58` (vs prediction `0.00%`, vs reactive `0.00%`).
- Response time: `nan s` (vs reactive `nan%`).
- Last-hour bird deterrence: `0.00%` (delta vs reactive `0.00` pts).
- Communication: `0.00` via `boundary_bytes_sent_mean`.
- Preventive completions / planner rejections: `1.00` / `41.00`.

### row_local_priority_queue: Row-Block Local Priority Queue
- Exposure: `5.58` (vs prediction `0.00%`, vs reactive `0.00%`).
- Response time: `nan s` (vs reactive `nan%`).
- Last-hour bird deterrence: `0.00%` (delta vs reactive `0.00` pts).
- Communication: `128.00` via `boundary_bytes_sent_mean`.
- Preventive completions / planner rejections: `0.00` / `0.00`.

## Manifest

- `s1_risk_open_core`: kind=`simplification_stage` output=`results\verify_last_hour_exploration_compare\s1_risk_open_core`
- `row_local_priority_queue`: kind=`exploration_variant` output=`results\verify_last_hour_exploration_compare\row_local_priority_queue`
