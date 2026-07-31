# System Input / Output Boundaries

This file documents the production-system boundaries introduced in Phase 1. The goal is to make it clear:
- which inputs belong to which subsystem,
- which file is responsible for each stage, and
- what outputs each stage produces.

Primary files:
- Orchestration: `DeterrentSystem.py`
- Structured config/state: `system_structure.py`
- Shared stage helpers: `system_stage_helpers.py`
- Forecast model: `SESTPP.py`
- Task generation / assignment: `TaskGenerator.py`

## 1. Structured inputs

The production simulator now builds a grouped config object at runtime:
- `system_config_structured`

Source:
- `DeterrentSystem.py`
- built by `build_production_system_config(...)` in `system_structure.py`

Sections in the structured config:
- `field_timing`
- `fleet`
- `zone_partitioning`
- `model`
- `detection`
- `task_generation`
- `task_priority`
- `gating`
- `planner`
- `baseline`
- `ground_truth`
- `forecast`
- `metrics`
- `motion`
- `idle_behavior`
- `deterring_modes`
- `habituation`
- `stl`

This does not change simulator behavior. It only groups the existing flat inputs into subsystem-aligned sections.

## 2. Subsystem responsibilities

### 2.1 Forecast / model

File:
- `SESTPP.py`

Consumes:
- `model`
- intervention feedback from completed deterrence
- recent detections / boundary events

Produces:
- updated `lam`
- hotspot field
- per-robot predictive state

### 2.2 Task generation

File:
- `TaskGenerator.py`

Consumes:
- `task_generation`
- `task_priority`
- `gating`
- `deterring_modes`
- `habituation`
- `stl`
- robot forecast state from `SESTPP.py`
- live robot poses when enabled for task planning
- recent detections and recent deterrence history
- habituation/STL adapters when `predictive_utility_mode="stl_robustness"`

Produces:
- candidate patrolling tasks
- candidate direct-detection deterring tasks
- candidate model-scored deterring tasks
- task-generation diagnostics

### 2.3 Assignment / planner / dispatch

Files:
- `TaskGenerator.py` (`TaskAssigner`)
- orchestration in `DeterrentSystem.py`

Consumes:
- `planner`
- `task_priority`
- generated task candidates
- robot load / task queue state

Produces:
- primary / secondary assignments
- planner rejections
- queue replacements
- active task set

### 2.4 Motion / execution

File:
- `DeterrentSystem.py`

Consumes:
- `motion`
- assigned goals
- row / headland geometry

Produces:
- per-robot motion commands / goals
- updated robot poses
- completed tasks
- travel / energy accumulation

ROS-oriented integration seam:
- `motion_orchestration_mode=local` keeps the current simulator-driven motion path
- `motion_orchestration_mode=command_only` turns the motion stage into a command-emission boundary so another system can own execution
- `motion_command_callback` can consume the per-step command batch without changing the planner/task logic
- `motion_state_callback` lets an external system feed poses back into the core loop so planning, completion checks, and metrics run on externally executed motion

### 2.5 Truth process and sensing

File:
- `DeterrentSystem.py`

Consumes:
- `ground_truth`
- `detection`

Produces:
- truth event stream
- detections seen by robots
- suppression outcomes
- habituation effectiveness updates and event-level `eta_at_apply`

Implementation note:
- per-step truth generation / legacy detection processing is now factored through `system_stage_helpers.py`

### 2.6 Metrics / reporting

File:
- `DeterrentSystem.py`

Consumes:
- outputs from all other stages

Produces:
- `metrics`
- `metrics_compact`
- debug / telemetry payloads

## 3. Structured runtime state

Each yielded production frame now also includes:
- `system_state_structured`

Source:
- built by `build_production_runtime_snapshot(...)` in `system_structure.py`

Sections in the structured runtime snapshot:
- `sim_time_s`
- `fleet`
- `tasks`
- `perception`
- `communication`
- `outputs`

This is a compact runtime summary, not a replacement for the raw frame fields.

## 4. Explicit task-pipeline stage outputs

Phase 2 adds two explicit stage outputs to the production frame:

### 4.1 Task generation stage

New key:
- `task_generation_structured`

Produced by:
- `_run_task_generation_stage(...)` in `DeterrentSystem.py`
- `TaskGenerationStageResult` in `system_structure.py`

Contains:
- whether patrol generation was enabled
- busy deterring robots
- candidate task count and preview
- pre-dispatch robot load snapshots
- task-generator diagnostics

### 4.2 Dispatch / admission stage

New key:
- `dispatch_structured`

Produced by:
- `_run_dispatch_stage(...)` in `DeterrentSystem.py`
- `DispatchStageResult` in `system_structure.py`

Contains:
- candidate count
- accepted task count and preview
- rejection counts by reason
- patrol replacement count
- post-dispatch robot load snapshots

This still preserves the old behavior. The difference is that the task pipeline now has named stage outputs instead of only side effects on `active_tasks`.

### 4.3 Motion / execution stage

New key:
- `motion_execution_structured`

Contains:
- motion orchestration mode and execution backend
- whether external motion feedback was applied this step
- how many robot poses were updated from external feedback this step
- per-robot motion commands for the current step
- per-robot motion state (`idle`, `moving`, `holding`)
- step movement distance by robot
- active goal count
- tasks completed this step by type
- stale-goal clears this step

### 4.4 Feedback / communication stage

New key:
- `feedback_structured`

Contains:
- recent deterrence events added this step
- intervention feedback applications this step
- boundary/intervention messages sent this step
- per-step communication byte deltas
- communication drop counters
- cumulative truth accepted / suppressed totals

### 4.5 Metrics stage

New key:
- `metrics_structured`

Contains a compact, stage-oriented summary of:
- exposure
- response time
- completed task total
- communication total
- fleet engagement / moving / idle fractions
- truth suppression rate
- forecast recall / precision
- habituation effectiveness summaries
- STL robustness clause summaries
- truth suppression opportunity/effect summaries

### 4.6 Truth / event-generation stage

New key:
- `truth_generation_structured`

Contains:
- whether ground-truth mode is active
- truth events added this step
- detections added this step
- truth candidate / accepted / suppressed counts this step
- cumulative truth candidate / accepted / suppressed totals
- cumulative suppression effect total

### 4.7 Forecast / model-update stage

New key:
- `forecast_model_structured`

Contains:
- SESTPP advance step size
- aggregate model-state summaries (`lam`, trigger mass, inhibition mass)
- whether forecast evaluation ran this step
- future-event / hotspot / hit counts from the forecast evaluation
- latest forecast recall / precision sample
- forecast sample total

Implementation note:
- per-step forecast evaluation and forecast-stage summary construction are now factored through `system_stage_helpers.py`

### 4.8 Telemetry / export stage

New key:
- `telemetry_structured`

Contains:
- whether telemetry is enabled
- pose update count this step
- robot diagnostic update count this step
- hotspot export count this step
- whether the telemetry flush was called
- target telemetry directory

Implementation note:
- telemetry emission and telemetry-stage summary construction are now factored through `system_stage_helpers.py`


### 4.9 Habituation / STL diagnostics

The habituation-aware STL integration adds diagnostic fields to existing stage outputs rather than adding a separate runtime stage.

Config sections:

- `habituation`
- `stl`

Task preview fields can include:

- `predictive_stl_U`
- `stl_summary`
- `stl_eta_at_apply`
- `predictive_action_variants`

Metric fields can include:

- `habituation_eta_mean`
- `habituation_eta_min`
- `habituation_eta_at_apply_mean`
- `habituation_variety_index`
- `stl_robustness_global_mean`
- `stl_robustness_global_min`
- `stl_robustness_exp`
- `stl_robustness_cov`
- `stl_robustness_hab`
- `truth_candidate_events`
- `truth_accepted_events`
- `truth_suppressed_events`
- `truth_suppression_effect_mean`
- `truth_suppression_effect_sum`
## 5. Frame outputs

The production frame output in `DeterrentSystem.py` now has three layers:

### 4.1 Raw simulation outputs

Existing keys such as:
- `poses`
- `robot_states`
- `robot_goals`
- `motion_commands`
- `truth_pts`
- `det_pts`
- `tasks_active`
- `tasks_done`
- `metrics`
- `metrics_compact`

### 4.2 Structured config output

New key:
- `system_config_structured`

Behavior:
- emitted once on the first frame
- `None` on later frames to avoid repeating the full config every step

### 4.3 Structured runtime-state output

New key:
- `system_state_structured`

Behavior:
- emitted every frame
- summarizes fleet, task, perception, communication, and compact output state

### 5.4 Structured stage outputs

New keys:
- `task_generation_structured`
- `dispatch_structured`
- `motion_execution_structured`
- `feedback_structured`
- `metrics_structured`
- `truth_generation_structured`
- `forecast_model_structured`
- `telemetry_structured`

Behavior:
- emitted every frame
- summarize the most recent truth, task-generation, dispatch, motion, feedback, forecast, telemetry, and metrics pass

## 6. Why this helps

This change is intended to make the system easier to understand without changing behavior:
- inputs are grouped by subsystem instead of living only in one giant function signature
- runtime state is summarized in one compact structure
- every major stage now has an explicit stage output
- the path from inputs -> subsystem -> outputs is explicit
- STL/habituation diagnostics make it possible to distinguish wiring failures from underpowered truth-suppression scenarios

## 7. Current limitation

This is still an intermediate refactor, but the main production loop is now externally visible as a staged pipeline.

It does **not** yet:
- extract the main loop into separate pipeline modules,
- change how tasks are generated or assigned,
- replace the existing raw frame fields.

The next logical step would be to extract explicit result objects for:
- zone repartitioning
- ground-truth / detection processing helpers as standalone modules
- motion / completion handling as standalone modules
