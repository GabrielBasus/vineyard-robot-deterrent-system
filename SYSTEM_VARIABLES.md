# System Variables Reference

This file inventories the externally changeable variables in the current codebase and groups them by subsystem.

Scope:
- Includes: function arguments, constructor arguments, CLI flags, and configurable dictionary keys used by the main production simulator, lab simulator, and active experiment runners.
- Excludes: transient local variables computed inside the loop, cached diagnostics, and legacy one-off scripts that do not expose reusable system configuration.

Primary source files:
- Production simulator: `DeterrentSystem.py:211`
- Production task generation / assignment: `TaskGenerator.py:24`, `TaskGenerator.py:70`, `TaskGenerator.py:503`
- Core point-process model: `SESTPP.py:40`, `SESTPP.py:80`
- Lab simulator: `DeterrentSystem_assignment_lab.py:213`
- Lab task generation / assignment: `TaskGenerator_lab.py:24`, `TaskGenerator_lab.py:99`, `TaskGenerator_lab.py:814`
- Production experiment runner: `run_24h_experiment_parallel.py:495`
- Lab diagnostics / confirm runners:
  - `compare_field_divergence_lab.py:478`
  - `run_field_divergence_confirm_lab.py:122`
  - `run_field_divergence_filter_sweep_lab.py:324`
  - `run_assignment_tuning_sweep_lab.py:1090`

## Named Planner Profiles

- `thesis_confirm` is the conservative post-fix planner preset for corrected counterfactual `predicted_deltaJ`, corrected intervention sharing, and corrected preventive admission ordering.
- Aliases: `post_fix`, `post-fix`.

Resolved values and rationale:
- `assigner_w_task_value = 0.20` - keeps task value as a moderate tie-break so corrected preventive value matters without overpowering distance and load costs.
- `model_deterring_window_s = 120.0` - keeps enough recent evidence to stabilize preventive scoring without dragging in stale detections.
- `model_deterring_min_persistence_replans = 3` - requires three consecutive replans before admission, filtering transient hotspots.
- `model_deterring_max_eta_s = 90.0` - rejects slow preventive dispatches that are unlikely to realize the corrected deltaJ.
- `model_deterring_score_margin = 0.20` - requires a meaningful gain over patrol before preventive work can displace patrol capacity.
- `model_deterring_budget_per_robot_per_hr = 3` - caps preventive admissions per robot so the target is yield, not raw preventive volume.
- `model_deterring_budget_mode = count_per_hour` - treats the budget as a hard preventive count cap in confirm/tuning presets.
- `model_deterring_gate_policy = sprt_capacity` - requires both evidence and available capacity instead of heuristic ranking alone.
- `model_deterring_chance_threshold = 0.25` - blocks lower-confidence preventive candidates after SPRT admission.
- `model_deterring_min_deltaJ_per_cost = 0.25` - raises the utility-per-cost floor above the loose `0.15` default so only stronger corrected candidates survive.

Activation:
- Production / lab simulator kwargs: `planner_profile="thesis_confirm"`.
- Confirm runner CLI / YAML: `--planner-profile thesis_confirm` or `planner.profile: thesis_confirm`.
- Assignment tuning runner CLI / YAML: `--planner-profile thesis_confirm` or `planner.profile: thesis_confirm`.

## 1. Production system variables

These are the main top-level inputs exposed by `run_simulation_frames_persistent(...)` in `DeterrentSystem.py`.

### 1.1 World, time, and fleet

- `W`, `H` - field width and height.
- `seed` - RNG seed.
- `dt` - simulation integration step.
- `T_end` - simulation horizon.
- `fps` - visualization / frame capture rate.
- `Nrobots` - robot count.
- `uav_fraction` - fraction of robots instantiated as UAVs.

### 1.2 Zone partitioning / area weighting

- `mode` - zone partitioning mode.
- `scale` - zone weighting / partition scale.
- `gamma` - zone health-to-weight sensitivity.
- `health_threshold` - optional trigger-only partition threshold.
- `debug_zone_areas` - enable zone-area debug output.

### 1.3 Forecast field / SESTPP grid

- `NX`, `NY` - grid resolution.
- `sigma` - excitation kernel spatial spread used by the robot model.
- `omega` - excitation temporal decay.
- `omega_inhib` - inhibition temporal decay used by the proposed model.
- `alpha_inhib` - intervention inhibition strength used by the proposed model.
- `mu_base` - background intensity baseline.
- `bg_ema` - background-rate EMA.

Related model API variables exposed by `OnlineSESTPP` in `SESTPP.py`:
- `alpha_in` - self-excitation strength.
- `alpha_cross` - cross-excitation strength.

Note:
- In the production simulator, `alpha_in` and `alpha_cross` are currently derived internally from `omega`.
- Production defaults are currently tuned to:
  - `omega_inhib = 900.0`
  - `alpha_inhib = 0.45`
  - `mu_base = 5e-5`
  - `bg_ema = 1e-6`

### 1.4 Detection / sensing / local event generation

- `detect_rate_per_robot` - nominal detection opportunity rate near each robot.
- `detect_sigma_m` - spatial noise / spread for detections.
- `bird_stay_mean_s` - mean bird linger time near a robot.
- `bird_detection_prob` - detection observation probability for an accepted ground-truth event within range; in the fallback local bird generator, the per-step detection probability while a bird is present.
- `per_robot_cooldown_s` - minimum time between detections for a given robot.
- `max_detections_per_step` - safety cap on detections per step.
- `detect_range_m` - maximum range for using ground-truth events as detections.

### 1.5 Task generation / refresh / immediate execution

- `task_replan_period_s` - planner refresh period.
- `arrival_radius_m` - distance threshold for task arrival.
- `hold_time_s` - required dwell time at a deterring task.
- `deterring_suppress_radius_m` - local suppression radius for temporary task suppression.
- `deterring_suppress_window_s` - temporary task suppression time window.
- `task_refresh_min_score` - minimum score for task refresh retention.
- `task_max_age_s` - stale-task lifetime.
- `enable_direct_detection_task_clustering` - enable spatiotemporal deduplication for direct-detection deterring tasks before assignment.
- `direct_detection_task_cluster_radius_m` - legacy shared default radius used by both direct-detection dedup stages when the split controls are not set.
- `direct_detection_task_cluster_window_s` - legacy shared default time window used by both direct-detection dedup stages when the split controls are not set.
- `direct_detection_task_active_refresh_radius_m` - spatial radius for refreshing an already active direct-detection task when a nearby new detection arrives.
- `direct_detection_task_active_refresh_window_s` - temporal window for refreshing an already active direct-detection task.
- `direct_detection_task_active_refresh_require_assigned` - only refresh an existing direct-detection task if it already has a primary robot assigned.
- `direct_detection_task_active_refresh_max_eta_s` - maximum assigned-robot ETA allowed for refreshing an active direct-detection task; slower tasks are left separate so a nearer reactive task can be spawned.
- `direct_detection_task_queued_cluster_radius_m` - spatial radius for clustering queued direct-detection tasks before assignment.
- `direct_detection_task_queued_cluster_window_s` - temporal window for clustering queued direct-detection tasks before assignment.
- `patrol_hotspot_filter_mode` - patrol hotspot filter mode (`absolute`, `percentile`, `top_k`).
- `patrol_hotspot_score_percentile` - percentile used when patrol hotspot filter mode is `percentile`.
- `patrol_hotspot_keep_top_k` - top-k used when patrol hotspot filter mode is `top_k`.
- `patrol_feedback_inhibition_retention` - fraction of intervention inhibition retained in patrol hotspot generation and patrol scoring only (`1.0` = current full feedback effect, `0.0` = uninhibited patrol scoring).

### 1.6 Task priority and planner cost weights

- `w_prio` - global task-priority weight.
- `prio_deterring` - deterring task priority.
- `prio_patrolling` - patrolling task priority.
- `assigner_w_load` - robot load penalty in assignment.
- `enable_assignment_task_value_term` - enable task-value term in assignment score.
- `assigner_w_task_value` - weight for task utility / score during assignment.
- `planner_profile` - optional named planner preset override (`thesis_confirm`, alias `post_fix`).

### 1.7 Preventive model-scored deterrence gating

- `model_deterring_window_s` - detection-history window for preventive candidates.
- `model_deterring_risk_threshold` - minimum risk confidence.
- `model_deterring_risk_scale` - risk-confidence scaling constant.
- `model_deterring_min_recent_points` - minimum recent support count.
- `model_deterring_field_threshold` - optional minimum field threshold.
- `model_deterring_min_persistence_replans` - minimum consecutive replans before emission.
- `model_deterring_persistence_max_gap_s` - allowed inactivity gap for persistence memory.
- `model_deterring_score_margin` - required margin over patrol score.
- `model_deterring_repeat_block_window_s` - repeat-block time window after recent preventive action.
- `model_deterring_repeat_block_radius_m` - repeat-block spatial radius.
- `model_deterring_max_eta_s` - maximum ETA allowed for preventive deterring.
- `model_deterring_busy_min_support_override` - relaxed support threshold when robot is busy.
- `model_deterring_busy_risk_override` - relaxed risk threshold when robot is busy.
- `model_deterring_budget_per_robot_per_hr` - preventive deterring count budget.
- `enable_predicted_deltaJ_gate` - enable explicit predicted-utility gate.
- `min_predicted_deltaJ_for_model_deterring` - minimum predicted utility for preventive deterring.
- `model_deterring_gate_policy` - preventive gate policy (`heuristic`, `sprt_capacity`).
- `model_deterring_sprt_alpha` - SPRT false-alarm control.
- `model_deterring_sprt_beta` - SPRT miss-rate control.
- `model_deterring_sprt_patch_radius_m` - spatial patch radius used for SPRT count expectations.
- `model_deterring_min_sprt_margin` - additional evidence margin required above the SPRT accept threshold before a preventive candidate is considered strong enough to continue.
- `model_deterring_chance_threshold` - event-probability threshold after SPRT admission.
- `model_deterring_min_deltaJ_per_cost` - minimum preventive utility-per-cost ratio.
- `model_deterring_min_selection_weight` - minimum posterior/evidence-weighted utility factor required before a model-scored preventive candidate can outrank patrol.
- `model_deterring_capacity_rho_max` - service-rate utilization cap for preventive admission.
- `model_deterring_capacity_history_window_s` - rolling history window for service-rate estimation.
- `model_deterring_capacity_min_completed_tasks` - minimum completed tasks needed before service-rate gating activates.
- `model_deterring_capacity_fallback_budget_per_hr` - fallback hourly preventive budget when service-rate history is insufficient.
- `model_deterring_budget_mode` - budget interpretation (`count_per_hour`, `utility_per_hour`).
- `model_deterring_budget_utility_per_robot_per_hr` - utility-budget rate.
- `model_deterring_global_admission_cap_per_cycle` - global cap on accepted model-scored preventive tasks per replan cycle.
- `model_deterring_require_idle_robot_for_admission` - legacy hard idle-only admission switch for model-scored preventive tasks.
- `model_deterring_prefer_idle_robots_for_assignment` - try idle eligible robots first when assigning model-scored preventive tasks.
- `model_deterring_busy_fallback_p_event_min` - minimum predicted event probability required before a busy robot may receive a model-scored preventive task.
- `model_deterring_busy_fallback_deltaJ_per_cost_min` - minimum utility-per-cost required before a busy robot may receive a model-scored preventive task.
- `model_deterring_busy_fallback_eta_s_max` - maximum ETA allowed for busy-robot fallback on model-scored preventive tasks.
- `protect_direct_detection_from_model_deterring` - block model-scored preventive tasks that conflict with active or recent direct-detection work.
- `model_deterring_direct_conflict_radius_m` - spatial conflict radius used when protecting direct-detection tasks.
- `model_deterring_direct_conflict_window_s` - recent-completion conflict window used when protecting direct-detection tasks.
- `protect_active_model_deterring_persistence` - preserve admitted model-scored preventive tasks across replans instead of aging them out immediately.
- `model_deterring_min_persistence_lifetime_s` - minimum lifetime for an active model-scored preventive task before generic stale-task pruning can remove it.
- `model_deterring_persistence_eta_multiplier` - scales the accepted task ETA into an adaptive persistence lock duration.
- `model_deterring_persistence_buffer_s` - fixed time buffer added on top of adaptive preventive persistence.
- `model_deterring_max_persistence_lifetime_s` - upper cap on adaptive preventive persistence duration.
- `model_deterring_lock_near_goal_radius_m` - near-goal radius that keeps an active model-scored preventive task locked until it can finish.
- `protect_active_model_deterring_goal_preemption` - allow a protected active model-scored preventive task to take over a robot's patrol goal while it remains locked.
- `enable_model_scored_deterring` - baseline toggle for preventive deterring.
- `auto_enable_proposed_preventive_window` - auto-set a nonzero preventive window for `proposed` when preventive deterring is enabled.
- `default_proposed_model_deterring_window_s` - default preventive-window value used by the auto-configuration.

### 1.8 Planner / dispatch / queue admission

- `max_active_tasks_per_robot` - total task cap per robot.
- `max_active_patrolling_per_robot` - patrol task cap per robot.
- `max_active_model_deterring_per_robot` - preventive deterring cap per robot.
- `preempt_deterring_goals` - allow deterring to preempt current goals.
- `preempt_direct_detection_goals` - allow direct-detection deterring to preempt.
- `preempt_model_scored_goals` - allow model-scored deterring to preempt.
- `protect_locked_model_deterring_from_patrol_assignment` - block new patrol assignments to a robot while a locked model-scored preventive task is still in progress.
- `use_live_robot_pose_for_task_planning` - use live robot poses, not zone centroids, for task ETA/scoring and assignment.

### 1.9 Baseline / mode selection

- `simulation_mode` - baseline selector (`reactive`, `prediction_only`, `proposed`).
- `enable_patrolling` - force patrol on/off.
- `enable_intervention_feedback` - force intervention feedback on/off.
- `include_fallback_patrol` - allow fallback patrol tasks.
- `enable_model_scored_deterring` - allow preventive deterring tasks.
- `enable_winner_profile` - opt-in production migration profile.

### 1.10 Deterrence action model

- `deterring_modes` - dictionary of deterrence modes and their parameters.

Each mode entry can define:
- `beta` - modeled suppression strength.
- `omega` - modeled suppression temporal decay.
- `sigma` - modeled suppression spatial spread.
- `w_eta` - ETA penalty multiplier for that mode.
- `fixed_cost` - additive fixed action cost.

Default modes in current code:
- `formation`
- `laser`
- `biosonic`

### 1.11 Ground-truth bird process

- `use_ground_truth` - enable event-driven truth process.
- `mu_true` - truth background rate.
- `alpha_true` - truth offspring mean.
- `omega_true` - truth temporal decay.
- `sigma_true` - truth spatial spread.
- `beta_true` - truth suppression strength.
- `use_mode_dependent_truth_suppression` - let each deterring mode use its own truth suppression parameters.
- `warmup_s` - truth-process warmup horizon before the visible run.

### 1.12 Forecast, telemetry, and evaluation

- `forecast_horizon_s` - forecast evaluation horizon.
- `forecast_match_radius_m` - spatial matching radius for forecast metrics.
- `forecast_top_k` - forecast top-k count.
- `forecast_eval_period_s` - forecast evaluation cadence.
- `event_viz_window_s` - recent event visualization window.
- `telemetry_dir` - telemetry output directory.
- `telemetry_clear_on_start` - clear telemetry directory before run.
- `telemetry_prompt_save` - prompt before preserving telemetry output.

### 1.13 Metrics, energy, and communication

- `response_match_radius_m` - response-time matching radius.
- `deterring_eval_radius_m` - realized deterrence evaluation radius.
- `deterring_eval_window_s` - realized deterrence evaluation window.
- `ugv_energy_per_m` - UGV energy cost per meter.
- `uav_energy_per_m` - UAV energy cost per meter.
- `bytes_per_boundary_msg` - bytes charged per boundary message.
- `bytes_per_intervention_msg` - bytes charged per intervention message.
- `intervention_boundary_min_interval_s` - minimum interval between boundary intervention messages.
- `intervention_boundary_spatial_quant_m` - spatial quantization used for intervention message dedupe.
- `intervention_boundary_min_weight` - minimum shared intervention weight.
- `report_metrics_end` - print / return final metrics summary.

### 1.14 Row geometry and motion constraints

- `motion_orchestration_mode` - motion execution mode (`local` or `command_only`) for external orchestration integration.
- `row_spacing_m` - vineyard row spacing.
- `row_width_m` - row width.
- `row_gain` - row value gain.
- `edge_gain` - edge value gain.
- `edge_scale_m` - edge-value decay scale.
- `headland_m` - headland width.
- `lane_eps_m` - lane snapping tolerance.
- `headland_space_m` - free headland spacing.
- `turn_space_m` - turn space allowance.
- `row_block_len_m` - blocked-row segment length.
- `row_block_gap_m` - blocked-row gap length.

### 1.15 Idle / demo behavior and debug

- `idle_roam_enabled` - allow idle robots to roam.
- `idle_roam_interval_s` - idle roam refresh interval.
- `idle_roam_jitter_m` - idle roam perturbation radius.
- `debug_movement` - enable movement debug output.
- `motion_command_callback` - optional runtime callback that consumes per-step motion commands; intended for integration wrappers rather than static config files.
- `motion_state_callback` - optional runtime callback that feeds externally executed robot poses back into the core loop.

## 2. Task generation and assignment API variables

These variables are not all surfaced by the production simulator directly, but they are still configurable API inputs in the current system.

### 2.1 `TaskGenerator` constructor (`TaskGenerator.py:24`)

- `merge_radius_m` - clustering / dedupe merge radius.
- `dedupe_xy_decimals` - spatial rounding precision for dedupe.
- `dedupe_t_decimals` - temporal rounding precision for dedupe.
- `patrol_cooldown_s` - per-robot patrol generation cooldown.

### 2.2 `TaskGenerator.periodic_patrolling(...)` (`TaskGenerator.py:70`)

Additional API-level tunables used in task generation:
- `hotspot_top_k` - number of hotspot seeds requested from the model.
- `min_hotspot_score` - absolute hotspot score threshold.
- `hotspot_spacing_m` - spacing used for hotspot thinning.
- `jitter_m` - patrol target jitter.
- `horizon_s` - planning horizon used in utility calculations.
- `weight_fn` - optional value-map override.
- `profiles` - robot capability profiles used in task scoring.
- `cost_w_eta` - ETA penalty scale in task scoring.
- `spinup_by_type` - per-robot-type spin-up times.
- `robot_poses` - live robot pose map used for ETA/cost evaluation.
- `preventive_capacity_remaining_by_robot` - per-robot preventive admission allowance.
- `preventive_capacity_ready_by_robot` - per-robot flag for whether service-rate gating is active.
- `replan_interval_s` - count window used by the research-backed gate.
- `value_edge_gain`, `value_edge_scale` - edge-value map terms.
- `value_block_gain`, `value_block_size` - block-value map terms.

Most preventive deterring gate variables listed in Section 1.7 are also passed through this API.

### 2.3 `TaskAssigner` configurable weight keys (`TaskGenerator.py:503`)

The `params` dictionary accepted by `TaskAssigner` can override:
- `w_cap`
- `w_eta`
- `w_stay`
- `w_zone`
- `w_health`
- `w_prio`
- `w_load`
- `w_task_value`
- `prio_deterring`
- `prio_patrolling`
- `uav_spinup_s`
- `ugv_spinup_s`
- `min_batt_deterring`
- `min_batt_patrolling`

## 3. Core point-process model variables

These are the model-level inputs exposed by `OnlineSESTPP` in `SESTPP.py`.

### 3.1 Constructor arguments (`SESTPP.py:40`)

- `x_min`, `x_max`, `y_min`, `y_max` - model domain bounds.
- `nx`, `ny` - model grid resolution.
- `sigma` - kernel spatial spread.
- `omega` - excitation decay.
- `omega_inhib` - inhibition decay.
- `alpha_in` - self-excitation magnitude.
- `alpha_cross` - cross-excitation magnitude.
- `alpha_inhib` - inhibition magnitude per intervention.
- `mu_base` - baseline intensity.
- `bg_ema` - background EMA coefficient.

### 3.2 Runtime setter (`SESTPP.py:80`)

The following can be changed at runtime via `set_params(...)`:
- `alpha_in`
- `alpha_cross`
- `alpha_inhib`
- `sigma`
- `omega`
- `omega_inhib`
- `bg_ema`

## 4. Lab-only simulator variables

These exist only in `DeterrentSystem_assignment_lab.py` / `TaskGenerator_lab.py`.

### 4.1 Patrol-filter experiments

- `patrol_min_hotspot_score` - patrol hotspot threshold.
- `patrol_hotspot_filter_mode` - local patrol hotspot filter policy (`absolute`, `percentile`, `top_k`).
- `patrol_hotspot_score_percentile` - percentile threshold when using percentile mode.
- `patrol_hotspot_keep_top_k` - kept hotspot count when using top-k mode.
- `patrol_feedback_inhibition_retention` - ablation knob for how strongly feedback inhibition reshapes patrol ranking (`1.0` full, `0.0` ignored for patrol only).

### 4.2 Assignment-method experiments

- `assignment_method` - assignment solver (`frozen_greedy`, `hungarian`, `auction`, `cbba`, depending on runner).
- `assignment_distance_cost_per_m` - travel cost term in lab assignment utility.
- `assignment_switch_penalty` - reassignment / switching penalty.
- `cbba_max_rounds` - CBBA consensus round cap.
- `cbba_epsilon` - CBBA numerical tie tolerance.

### 4.3 Research gate experiments

- `model_deterring_gate_policy` - preventive gate policy (`heuristic`, `sprt_capacity`).
- `model_deterring_sprt_alpha` - SPRT false-alarm control.
- `model_deterring_sprt_beta` - SPRT miss-rate control.
- `model_deterring_sprt_patch_radius_m` - patch radius for SPRT counts.
- `model_deterring_min_sprt_margin` - extra evidence margin above the SPRT accept boundary.
- `model_deterring_chance_threshold` - event-probability threshold after SPRT.
- `model_deterring_min_deltaJ_per_cost` - minimum utility-per-cost ratio.
- `model_deterring_min_selection_weight` - minimum posterior/evidence-weighted selection factor.
- `model_deterring_capacity_rho_max` - queue utilization cap for preventive admission.
- `model_deterring_capacity_history_window_s` - rolling history window for capacity estimation.
- `model_deterring_capacity_min_completed_tasks` - minimum history required before using service-rate gating.
- `model_deterring_capacity_fallback_budget_per_hr` - fallback preventive budget when service-rate history is insufficient.

### 4.4 Lab-only debug export flags

- `export_field_debug` - export field-level debug snapshots.
- `export_task_debug` - export task / patrol pipeline debug snapshots.

## 5. Production experiment runner variables

`run_24h_experiment_parallel.py` does not introduce a second simulator; it sweeps and forwards production variables.

### 5.1 Runner controls (`run_24h_experiment_parallel.py:495`)

- `profile`
- `max-workers`
- `num-runs`
- `seed-start`
- `dt`
- `nx`
- `ny`
- `limit-settings`
- `tune-preset`
- `scenario-scope`
- `time-horizons-h`
- `time-metrics-period-s`
- `enable-winner-profile`
- `winner-profile-id`

### 5.2 Production variables changed by tune presets

The runner varies subsets of the production simulator variables already listed in Section 1, mainly:
- `task_replan_period_s`
- `prio_deterring`
- `prio_patrolling`
- `deterring_modes` (through beta / cost scaling)
- `model_deterring_window_s`
- `model_deterring_risk_threshold`
- `model_deterring_risk_scale`
- `model_deterring_budget_per_robot_per_hr`
- `model_deterring_min_recent_points`
- `model_deterring_min_persistence_replans`
- `model_deterring_score_margin`
- `model_deterring_repeat_block_window_s`
- `model_deterring_repeat_block_radius_m`
- `model_deterring_max_eta_s`
- `model_deterring_busy_min_support_override`
- `model_deterring_busy_risk_override`
- `max_active_tasks_per_robot`
- `max_active_patrolling_per_robot`
- `max_active_model_deterring_per_robot`
- `preempt_deterring_goals`
- `preempt_direct_detection_goals`
- `preempt_model_scored_goals`
- `intervention_boundary_min_interval_s`
- `intervention_boundary_spatial_quant_m`
- `intervention_boundary_min_weight`
- `assigner_w_load`

## 6. Lab diagnostics / confirm runner variables

### 6.1 Shared field-divergence A/B controls

These are exposed by both:
- `compare_field_divergence_lab.py:478`
- `run_field_divergence_confirm_lab.py:122`

Common controls:
- `seed` / `seeds`
- `t-end`
- `dt`
- `sample-period-s`
- `hotspot-top-k`
- `hotspot-match-radius-m`
- `patrol-match-radius-m`
- `recent-deterrence-window-s`
- `recent-deterrence-radius-m`
- `local-patch-radius-m`
- `assignment-method`
- `assignment-distance-cost-per-m`
- `assignment-switch-penalty`
- `task-replan-period-s`
- `assigner-w-task-value`
- `planner-profile`
- `patrol-min-hotspot-score`
- `patrol-hotspot-filter-mode`
- `patrol-hotspot-score-percentile`
- `patrol-hotspot-keep-top-k`
- `model-deterring-window-s`
- `model-deterring-gate-policy`
- `model-deterring-sprt-alpha`
- `model-deterring-sprt-beta`
- `model-deterring-chance-threshold`
- `model-deterring-min-deltaj-per-cost`
- `truth-beta-scale`
- `truth-omega-scale`
- `truth-sigma-scale`
- `model-beta-scale`
- `outdir`

### 6.2 Confirm-runner-only planner controls (`run_field_divergence_confirm_lab.py`)

- `model-deterring-min-persistence-replans`
- `model-deterring-max-eta-s`
- `model-deterring-score-margin`
- `model-deterring-budget-per-robot-per-hr`
- `model-deterring-budget-mode`
- `model-deterring-budget-utility-per-robot-per-hr`

### 6.3 Filter-sweep-only controls (`run_field_divergence_filter_sweep_lab.py:324`)

Additional sweep dimensions:
- `patrol-filter-modes`
- `patrol-percentiles`
- `patrol-keep-top-k-values`
- `task-replan-period-values`
- `model-deterring-gate-policies`
- `model-deterring-sprt-alpha-values`
- `model-deterring-chance-threshold-values`
- `model-deterring-min-deltaj-per-cost-values`

## 7. Assignment-tuning lab runner variables

These are the top-level sweep controls for `run_assignment_tuning_sweep_lab.py:1090`.

### 7.1 Runner / sweep controls

- `stage`
- `num-runs`
- `seed-start`
- `t-end`
- `dt`
- `baselines`
- `methods`
- `distance-costs`
- `switch-penalties`
- `replan-periods`
- `assigner-w-task-values`
- `planner-profile`
- `phase1-manifest`
- `use-phase1-winner`
- `outdir`
- `resume`
- `checkpoint-path`
- `max-workers`

### 7.2 Preventive-gating sweep controls

- `gate-policies`
- `sprt-alpha-values`
- `sprt-beta-values`
- `chance-threshold-values`
- `min-deltaj-per-cost-values`
- `capacity-rho-max-values`
- `risk-thresholds`
- `min-persistence-replans`
- `max-eta-values`
- `score-margin-values`
- `budget-per-hr`
- `budget-modes`
- `budget-utility-per-hr`
- `deterring-windows`
- `min-predicted-deltaj-values`
- `beta-true-values`

## 8. Practical reading order

If you are changing the system by hand, the most important files to inspect in order are:

1. `DeterrentSystem.py` - production top-level simulator inputs.
2. `TaskGenerator.py` - patrol / preventive task creation and assignment weights.
3. `SESTPP.py` - model-level process parameters.
4. `DeterrentSystem_assignment_lab.py` and `TaskGenerator_lab.py` - lab-only assignment, gating, and patrol-filter variants.
5. Runner scripts - only if you are launching sweeps or confirm studies.

## 9. Recommended next cleanup

This inventory is complete enough to use as a parameter map, but it is not yet a single machine-readable manifest.

If you want a stricter configuration interface, the next useful step is:
- move the top-level simulator arguments into a structured config object, and
- generate this markdown automatically from that config schema.
