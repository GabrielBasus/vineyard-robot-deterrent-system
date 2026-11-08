# Thesis Dispatch Unit Tests

This document explains the focused `unittest` coverage for the April thesis dispatch reframe and the follow-on action refactor.

The goal of this test set is to verify five things:

1. The new canonical action model is correct.
2. The per-robot reservation-window accounting is correct.
3. Dispatch ordering and reserved-capacity policy behavior are correct.
4. Structured exports expose the new action and thesis metrics cleanly.
5. The new thesis-facing `tau_service_s` parameter changes runtime behavior correctly while preserving compatibility with `hold_time_s`.

The main files covered here are:

- [tests/test_action_schema.py](/c:/Users/gabri/Documents/CalPoly/Thesis/Code/tests/test_action_schema.py)
- [tests/test_robot_dispatch_time_tracker.py](/c:/Users/gabri/Documents/CalPoly/Thesis/Code/tests/test_robot_dispatch_time_tracker.py)
- [tests/test_dispatch_priority_ordering.py](/c:/Users/gabri/Documents/CalPoly/Thesis/Code/tests/test_dispatch_priority_ordering.py)
- [tests/test_motion_command_actions.py](/c:/Users/gabri/Documents/CalPoly/Thesis/Code/tests/test_motion_command_actions.py)
- [tests/test_tracking_state_exports.py](/c:/Users/gabri/Documents/CalPoly/Thesis/Code/tests/test_tracking_state_exports.py)
- [tests/test_thesis_dispatch_reframe.py](/c:/Users/gabri/Documents/CalPoly/Thesis/Code/tests/test_thesis_dispatch_reframe.py)

## How To Run

Run the full focused suite:

```powershell
python -m unittest `
  tests.test_action_schema `
  tests.test_robot_dispatch_time_tracker `
  tests.test_dispatch_priority_ordering `
  tests.test_motion_command_actions `
  tests.test_tracking_state_exports `
  tests.test_thesis_dispatch_reframe
```

Run one file:

```powershell
python -m unittest tests.test_thesis_dispatch_reframe
```

Run one specific test method:

```powershell
python -m unittest tests.test_thesis_dispatch_reframe.ThesisDispatchRuntimeTests.test_tau_service_alias_shortens_deterring_completion_and_falls_back_to_hold_time
```

Run a syntax check on the implementation files touched by this subsystem:

```powershell
python -m py_compile `
  action_schema.py `
  TaskGenerator.py `
  DeterrentSystem.py `
  system_structure.py `
  system_stage_helpers.py
```

If a test passes, `unittest` ends with `OK`. If a test fails, the traceback points to the exact assertion that broke.

## What Each Test File Covers

### 1. Action Schema

File:
- [tests/test_action_schema.py](/c:/Users/gabri/Documents/CalPoly/Thesis/Code/tests/test_action_schema.py)

This is the lowest-level unit test file. It checks the pure helpers in [action_schema.py](/c:/Users/gabri/Documents/CalPoly/Thesis/Code/action_schema.py).

Tests:

- `test_make_detection_action`
  Verifies that a direct detection becomes `ActionSpec(kind="deterring", name="direct_detection", params={}, service_time_s=...)`.

- `test_make_deterring_mode_action_uses_mode_params`
  Verifies that a model-scored deterring action such as `laser` picks up the correct mode parameters from `deterring_modes`.

- `test_make_patrol_action_maps_origin_to_name`
  Verifies that patrol origin is normalized into canonical action names such as `fallback_patrol` and `hotspot_patrol`.

- `test_task_action_reconstructs_direct_detection`
  Verifies that a legacy task row with `type="deterring"` and no mode is reconstructed as the canonical direct-detection action.

- `test_task_action_reconstructs_model_deterring`
  Verifies that a legacy task row with a deterrence `mode` is reconstructed as the correct canonical model-scored action.

- `test_task_action_reconstructs_patrol`
  Verifies that a legacy patrol task row is reconstructed as a canonical patrolling action with zero service time.

- `test_task_action_accessors_are_compatibility_stable`
  Verifies that the compatibility accessors `task_action_kind(...)`, `task_action_name(...)`, and `task_action_service_time_s(...)` return stable values for the rest of the runtime.

Why this matters:
- If this file passes, the new action model is internally consistent before the simulator ever runs.

### 2. Reservation Window / Per-Robot Time Accounting

File:
- [tests/test_robot_dispatch_time_tracker.py](/c:/Users/gabri/Documents/CalPoly/Thesis/Code/tests/test_robot_dispatch_time_tracker.py)

This verifies the rolling-window accounting used by the reserved-capacity policy in [Robot.py](/c:/Users/gabri/Documents/CalPoly/Thesis/Code/Robot.py).

Tests:

- `test_tracker_prunes_partial_segments_and_reports_fractions`
  Verifies that the sliding window drops expired time correctly and reports the correct reactive, predictive, and idle fractions.

- `test_robot_wrapper_exposes_predictive_share`
  Verifies that the `Robot` wrapper correctly exposes recent predictive share through `dispatch_time_allocation(...)` and `predictive_share(...)`.

Why this matters:
- The `res` policy depends on recent predictive share. If this file fails, reservation claims are not trustworthy.

### 3. Dispatch Ordering

File:
- [tests/test_dispatch_priority_ordering.py](/c:/Users/gabri/Documents/CalPoly/Thesis/Code/tests/test_dispatch_priority_ordering.py)

This is a focused policy-ordering test for the candidate ordering helpers in [DeterrentSystem.py](/c:/Users/gabri/Documents/CalPoly/Thesis/Code/DeterrentSystem.py).

Tests:

- `test_direct_detection_stays_first_and_preventive_beats_low_patrol`
  Verifies that direct-detection tasks remain first in ordering, strong predictive deterrence beats weak patrol, the preview labels the canonical `action` correctly, and an active patrol can be selected for replacement when a stronger predictive task arrives.

- `test_weaker_preventive_does_not_displace_existing_patrol`
  Verifies that a weak predictive deterring task does not evict a stronger currently active patrol task.

- `test_regular_order_uses_eta_after_value_and_delta_terms`
  Verifies that when preventive tasks have similar value terms, ETA still breaks ties in the intended direction.

Why this matters:
- If this file passes, the thesis reframe did not accidentally break the local task-ordering contract.

### 4. Motion Command Action Export

File:
- [tests/test_motion_command_actions.py](/c:/Users/gabri/Documents/CalPoly/Thesis/Code/tests/test_motion_command_actions.py)

This is a narrow interface test for [system_stage_helpers.py](/c:/Users/gabri/Documents/CalPoly/Thesis/Code/system_stage_helpers.py).

Test:

- `test_motion_command_exposes_action_metadata`
  Verifies that when a task with a canonical `action` is turned into a motion command, the public export includes:
  `assigned_task_stream`,
  `assigned_action_kind`,
  `assigned_action_name`,
  `assigned_action_service_time_s`.

Why this matters:
- This proves the new action model is visible outside the planner/runtime core.

### 5. Tracking / Structured Export Surface

File:
- [tests/test_tracking_state_exports.py](/c:/Users/gabri/Documents/CalPoly/Thesis/Code/tests/test_tracking_state_exports.py)

This is a short runtime smoke test for the exported simulation snapshot structure.

Test:

- `test_tracking_state_is_exposed_when_enabled`
  Runs a very short simulation with tracking enabled and verifies that:
  `tracking_state` exists,
  runtime tracking includes robot and task-generator state,
  `system_state_structured` includes tracking,
  motion commands include the new action metadata fields.

Why this matters:
- This confirms that the debug/inspection surface still works after the action refactor.

### 6. Thesis Dispatch Reframe

File:
- [tests/test_thesis_dispatch_reframe.py](/c:/Users/gabri/Documents/CalPoly/Thesis/Code/tests/test_thesis_dispatch_reframe.py)

This is the main thesis-policy test file. It mixes pure helper checks and short runtime smoke checks.

#### Helper-Level Tests

- `test_dispatch_policy_settings_accept_res_rand_alias`
  Verifies that `res-rand` is normalized into `dispatch_policy="res"` plus `predictive_selection_policy="random"`.

- `test_reactive_override_slack_uses_task_age_and_eta`
  Verifies the reactive override slack formula:
  `slack = reactive_override_slack_s - age - eta`.

- `test_reserved_policy_prefers_predictive_when_share_below_target`
  Verifies the core reserved-capacity claim: if a robot's predictive share is below `reservation_fraction`, predictive work is selected before normal reactive fallback.

- `test_unconstrained_policy_keeps_reactive_first`
  Verifies that the `unc` baseline preserves the intended reactive-first behavior.

- `test_urgent_reactive_override_beats_predictive_claim`
  Verifies that urgent reactive tasks override the reservation claim when slack is exhausted.

- `test_random_predictive_selection_is_seeded`
  Verifies that the random predictive chooser is reproducible for a fixed RNG seed.

#### Runtime Smoke Tests

- `test_react_policy_blocks_predictive_admissions_but_keeps_generation`
  Runs a short simulation and verifies that `react` still generates predictive candidates for funnel accounting, but admits none of them.

- `test_reserved_policy_emits_stream_and_time_allocation_metrics`
  Verifies that `res` produces the thesis-facing structured outputs and metrics:
  candidate stream counts,
  accepted stream counts,
  per-robot predictive-share snapshots,
  dispatch stream counts,
  predictive completion counts,
  robot predictive/idle fractions,
  reactive load estimate.

- `test_runtime_snapshot_preserves_canonical_action_metadata`
  Uses short targeted runtime scenarios to verify that the runtime snapshot/export surfaces include canonical actions for:
  direct detection,
  patrol,
  model-scored deterrence.

- `test_tau_service_alias_shortens_deterring_completion_and_falls_back_to_hold_time`
  Verifies the new thesis-facing `tau_service_s` parameter.
  It checks two behaviors:
  a shorter `tau_service_s` causes more reactive deterring completions in the same short horizon,
  and omitting `tau_service_s` falls back to `hold_time_s`.

Why this matters:
- If this file passes, the thesis policy layer, the new service-time surface, and the runtime export contract are all behaving as intended in short end-to-end runs.

## Recommended Test Order

If you are debugging a failure, run the tests in this order:

1. `tests.test_action_schema`
2. `tests.test_robot_dispatch_time_tracker`
3. `tests.test_dispatch_priority_ordering`
4. `tests.test_motion_command_actions`
5. `tests.test_tracking_state_exports`
6. `tests.test_thesis_dispatch_reframe`

That order goes from pure deterministic helpers to short full-runtime smokes.

## How To Interpret Failures

- If `test_action_schema.py` fails:
  The canonical action model or compatibility resolver layer is wrong.

- If `test_robot_dispatch_time_tracker.py` fails:
  The reserved-capacity window accounting is wrong, so `reservation_fraction` decisions may be invalid.

- If `test_dispatch_priority_ordering.py` fails:
  The local ordering contract changed, likely in candidate ranking or patrol replacement logic.

- If `test_motion_command_actions.py` or `test_tracking_state_exports.py` fails:
  The runtime may still work internally, but the structured/export interfaces are no longer exposing the new action fields correctly.

- If `test_thesis_dispatch_reframe.py` fails:
  The thesis-facing dispatch behavior, stream accounting, or `tau_service_s` runtime behavior changed.

## One-Command Verification

For a fast "did the thesis dispatch/action refactor still work?" check, use:

```powershell
python -m unittest `
  tests.test_action_schema `
  tests.test_robot_dispatch_time_tracker `
  tests.test_dispatch_priority_ordering `
  tests.test_motion_command_actions `
  tests.test_tracking_state_exports `
  tests.test_thesis_dispatch_reframe
```

This is the best focused regression command for the new thesis dispatch/action subsystem.
