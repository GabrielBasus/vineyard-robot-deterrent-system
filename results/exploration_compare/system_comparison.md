# Cross-System Performance Comparison

Systems were run on matched seeds and summarized using the proposed baseline plus its paired gains over `prediction_only` and `reactive`.

## Highlights

- Best exposure: `s1_risk_open_core` at `775.72` with `-0.01%` vs reactive.
- Best response time: `s5_current_thesis_profile` at `27.27 s`.
- Best bird-deterrence: `s1_risk_open_core` at `4.40%`.
- Best balanced rank: `s1_risk_open_core` with overall rank `2.20`.

## Systems

### s1_risk_open_core: Main Core With Risk Gate Open
- Exposure: `775.72` (vs prediction `4.54%`, vs reactive `-0.01%`).
- Response time: `27.78 s` (vs reactive `49.99%`).
- Bird deterrence: `4.40%` (delta vs reactive `3.28` pts).
- Communication: `744.00` via `boundary_bytes_sent_mean`.
- Preventive completions / planner rejections: `14.00` / `26003.33`.
- Delta vs reference `s5_current_thesis_profile`: exposure `-35.09`, response `0.51 s`, birds `4.09` pts.

### row_local_priority_queue_frequent_repartition: Frequent Repartition + Near-Task Bias
- Exposure: `780.01` (vs prediction `0.00%`, vs reactive `4.07%`).
- Response time: `50.64 s` (vs reactive `16.65%`).
- Bird deterrence: `0.57%` (delta vs reactive `0.06` pts).
- Communication: `634.67` via `boundary_bytes_sent_mean`.
- Preventive completions / planner rejections: `0.00` / `10276.67`.
- Delta vs reference `s5_current_thesis_profile`: exposure `-30.80`, response `23.37 s`, birds `0.25` pts.

### row_local_priority_queue: Row-Block Local Priority Queue
- Exposure: `784.16` (vs prediction `0.00%`, vs reactive `2.54%`).
- Response time: `71.82 s` (vs reactive `-4.07%`).
- Bird deterrence: `1.06%` (delta vs reactive `0.56` pts).
- Communication: `1109.33` via `boundary_bytes_sent_mean`.
- Preventive completions / planner rejections: `0.00` / `123.33`.
- Delta vs reference `s5_current_thesis_profile`: exposure `-26.65`, response `44.55 s`, birds `0.75` pts.

### s5_current_thesis_profile: Current Thesis Profile
- Exposure: `810.81` (vs prediction `0.00%`, vs reactive `-3.80%`).
- Response time: `27.27 s` (vs reactive `50.31%`).
- Bird deterrence: `0.31%` (delta vs reactive `-0.80` pts).
- Communication: `829.33` via `boundary_bytes_sent_mean`.
- Preventive completions / planner rejections: `0.00` / `270.33`.
- Delta vs reference `s5_current_thesis_profile`: exposure `0.00`, response `0.00 s`, birds `0.00` pts.

### s0_simple_tasks_core: Simple Tasks Core
- Exposure: `792.23` (vs prediction `0.00%`, vs reactive `-0.29%`).
- Response time: `81.37 s` (vs reactive `-6.57%`).
- Bird deterrence: `0.50%` (delta vs reactive `-1.05` pts).
- Communication: `3576.00` via `boundary_bytes_sent_mean`.
- Preventive completions / planner rejections: `0.00` / `2737.33`.
- Delta vs reference `s5_current_thesis_profile`: exposure `-18.58`, response `54.10 s`, birds `0.18` pts.

## Manifest

- `s0_simple_tasks_core`: kind=`simplification_stage` output=`results\exploration_compare\s0_simple_tasks_core`
- `s1_risk_open_core`: kind=`simplification_stage` output=`results\exploration_compare\s1_risk_open_core`
- `s5_current_thesis_profile`: kind=`simplification_stage` output=`results\exploration_compare\s5_current_thesis_profile`
- `row_local_priority_queue`: kind=`exploration_variant` output=`results\exploration_compare\row_local_priority_queue`
- `row_local_priority_queue_frequent_repartition`: kind=`exploration_variant` output=`results\exploration_compare\row_local_priority_queue_frequent_repartition`
