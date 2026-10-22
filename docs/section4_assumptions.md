# Section 4: The plan decision procedure (implementation and assumptions)

This document describes the decision procedure of the improvement plan (Plan Sections 4
and 5) as implemented by `planner_procedure="plan"`. It replaces the earlier description of
the B4-pipeline continuation rollout (`stl_valuation_mode="continuation_rollout"`, variants
D and E), which were dropped from the evaluation by Section 6 decision 4; that code is kept
only for reproduction of earlier results.

Line numbers refer to commit `704722c` (branch `thesis-improvement`, updated 2026-10-22). `plan_procedure.py`
and `scenario_rollout.py` are being edited concurrently; when they move, search for the
named function.

Abbreviations: `PP` = `habituation_stl/plan_procedure.py`, `SR` =
`habituation_stl/scenario_rollout.py`, `DS` = `DeterrentSystem.py`, `RPC` =
`experiments/run_plan_completion.py`.

## 1. What the executed system is

The executed system is **B5 plus admitted predictive deviations** (PP:1-11). At every
replan the simulator runs its normal B5 pipeline (generation, `unc` dispatch, freshest-cue
rule). Before it does, the procedure may commit *deviations*: forced-first deterrence tasks
(robot, x, y, cue) that the robot executes first and then rejoins B5 (`SR.forced_task_row`,
SR:535; executed by DS:8522-8534). A robot without a deviation does exactly what B5 does, so
the executed fallback is the first action of the baseline continuation pi_0.

The simulator accepts `planner_procedure="plan"` only for the pipeline the rollout engine
mirrors (DS:8236-8255): `dispatch_policy="unc"`, lane-projection motion, local motion
orchestration, mixed predictive topology, no deferred action selection, pass-through
pre-assignment, ground truth on, no idle roaming, background events stamped at the step start.

Variants (RPC, `PLAN_VARIANTS`; all B5-based with NO reservation, final user decision
2026-10-22): `D_plan` (no service protection), `E_plan` (service
protection; confirmatory system, decision 2), `E_plan_tr` (+ timed recovery, Plan Eq. 4,
exploratory), `E_plan_floor` (+ effectiveness floor 0.4, decision 26), `C_plan` (one-intervention
Eq. 3 valuation, no service protection, decision 8). All run in `PLAN_ENV` (legacy estimator,
coupled random streams, complete truth deterrence memory, `stl_forecast_correction=True`).

## 2. Algorithm: Plan Section 5 steps 1-6 with code locations

Called at Stage 3 of a step whose replan is due, before the B5 replan (DS:8460-8466:
`active_tasks.extend(plan_proc.decide(locals()))`). The simulator clock is frozen while the
procedure computes.

**Step 1. Reconstruct and freeze one snapshot.**
`PP.decide` (PP:562) builds `SR.decision_snapshot_from_sim_locals(L, ...)` (PP:574; SR:3745).
`start_stage="replan"`: exactly the state the B5 dispatcher is about to see (truth and expiry
stages of step t done, nothing of the replan done). The policy side (robots, their
estimators, tasks, TaskGenerator state, planner habituation, commitments) is planner
information; the world (background, excitation parents, suppression terms, cue parameters)
is the planner's belief (`SR.planner_forecast_from_sim_locals`, SR:3611). Pending reactive
tasks get deadlines d_j = creation + `reactive_override_slack_s` (90 s). The horizon must
cover every pending deadline (assertion PP:584). With an information provider (decision 17,
per-robot information sets), the snapshot is restricted to what reached the decision's
robots (PP:576-581, `SR.restrict_snapshot_to_information`, SR:3827); `None` = instant full
sharing.

**Step 2. Baseline continuation.** pi_0 = the B5 decision rule mirrored in the engine
(`SR._Sim`, SR:1331) continued from the snapshot for horizon H (`forecast_horizon_s`,
300 s). Evaluated together with the candidates in step 3 (pi_0 is policy 0 of every
evaluation).

**Step 3. Candidates and their continuations.** Candidates are every (robot, preventive seed,
cue) pair that B5's own generation scores at t (`SR.generation_details`, SR:3926;
`PP.generate_candidates`, PP:537). Before evaluation a candidate is excluded if its robot
already executes a deviation (`robot_committed`). Reservation (final user decision
2026-10-22): there is NO reservation in the plan variants (no ceiling, no floor; the
predictive share is only logged with each decision). The B4-based variants A, B, C, C_gate
keep the submitted B4 floor, so the step C_gate -> C_plan also changes the reservation
(floor -> none). Code at `e3ec247`. pi_0 and all remaining candidates are
evaluated by `SR.evaluate` (SR:3240; via `PP.RolloutEngine`, PP:181) with **16 Monte Carlo
scenarios and common random numbers**: one scenario tree of exogenous events per scenario
(`SR._sample_scenario_tree`, SR:684), shared by every policy; action-dependent intensities,
detections and tasks are simulated inside each policy's rollout. Each candidate's
continuation is "candidate first, then B5" (engine rule R12, SR:177).

**Step 4. Feasibility and explicit relaxation.** Per candidate, in this order (PP:681-700):
* `infeasible_service` (service protection, E only): F0^s = {j : C^s_j(pi_0) <= d_j} per
  scenario s; reject if any j in F0^s has C^s_j(pi_a) > d_j in any scenario
  (`PP.service_feasibility`, PP:287). Uncompleted or dropped tasks have C = +inf.
* `infeasible_late` (E only, `plan_protect_late_tasks=True`): a baseline-late task with
  finite C^s_j(pi_0) must not finish later under pi_a.
* `infeasible_obligation` (timed recovery only): an obligation pi_0 satisfies in a scenario
  must be satisfied by pi_a in that scenario.
* `floor` (E_plan_floor only): planner q_hat at the candidate's application < 0.4 in any
  scenario where it is applied (never-applied candidates are exempt; decision 26).
Obligation relaxation (decision 28, PP:703-721): an obligation that neither pi_0 nor any
otherwise feasible candidate satisfies in every scenario is kept as a **bounded
violation**: it imposes no dominance constraint, and selection minimises its exceedance
(step 5). `plan_obligation_relaxation="drop"` reproduces the earlier rule.

**Step 5. Selection and admission.** Admit only if the Monte Carlo gate passes:
U_mean > eps_gate + k * U_se with eps_gate = 0 and k = 2 (user decision 2026-10-18; PP:697),
U(a) = J_H(pi_0) - J_H(pi_a) paired over scenarios. Among admissible candidates of ALL robots
the fleet-wide argmax of U is committed (PP:787); with bounded obligations the choice is
lexicographic: smallest mean-over-scenarios exceedance of E_low summed over the kept
obligations, then largest U, and a candidate is chosen only if its exceedance is not larger
than pi_0's (PP:769-784). The committed deviation is added to the snapshot and the remaining
robots' candidates are re-evaluated (sequential commitment, multiagent rollout; PP:799-845),
until no candidate is admissible, none remain, or the budget is exhausted. Executing "its
first action" = injecting the forced-first task; B5 then replans around it.

**Step 6. Record and replan.** Each decision appends a JSONL record (PP:874-916): every
candidate with its per-round U mean/SE, J, q_hat range at application, rejection reason and
final status (`REJECTION_REASONS`, PP:90); per round J0, F0 sizes, evaluation wall time and
the terminal summary (decision 30: unfinished tasks by stream, residual exposure rate and
busy robots at t + H, per policy and scenario); the admitted deviations with B5's own rank
of the same choice (decision 12) and predicted travel (decision 13); runtime and timeout
flag; F0-protected tasks (decision 29). At run end `PP.finalize` (PP:1036) attaches realized
exposure over [t, t + H], realized travel of deviations and the realized deadline outcome of
F0-protected tasks, and `PP.summary_metrics` (PP:1057) returns the run metrics. Replanning at
the next `task_replan_period_s` (45 s) uses fresh observations; outstanding timed-recovery
obligations persist across replans (`PP.monitor`, PP:488, called every step at DS:8456).

## 3. Runtime measurement

* Per decision: `runtime_s` = wall clock from entry of `decide` to the end of selection
  (`time.perf_counter`, PP:569 and PP:853), excluding the oracle evaluation (which runs
  after, PP:913-915, and is a diagnostic). Per round `eval_wall_s` (engine wall time).
* Per run: `plan_runtime_mean_s`, `plan_runtime_p95_s`, `plan_runtime_p99_s`,
  `plan_runtime_max_s`, `plan_candidates_per_decision_mean`, `plan_evaluated_candidates_total`.
* Evaluation runs use no budget (`plan_compute_budget_s=1e9`, decision 16): the simulator
  clock is frozen during planning, so a budget would only add machine-load dependence.
  Runtimes therefore depend on the rollout pool size (memory-capped, at most 12 workers) and
  on concurrent load: the evaluation (`run_plan_studies --study all`) runs two plan runs at
  once AND overlaps ordinary simulations with them (user decision 2026-10-22), so the
  quantiles describe that loaded machine, not an idle one or a real-time guarantee. The
  timeout study (45 s budget) runs in ISOLATION after everything else, one run at a time with
  nothing else running (user decision 2026-10-22).

## 4. Fallback behavior

* **No admissible candidate:** nothing is injected; every robot executes B5 (the first
  action of pi_0).
* **Timeout** (`plan_compute_budget_s`; exploratory timeout study only, 45 s): the
  evaluation is cancelled when the wall-clock deadline passes (`SR.EvaluationTimeout`,
  SR:3232); deviations committed in earlier rounds of the same decision stay committed;
  every candidate not decided gets status `timeout`; the worker pool is killed and restarted
  so the next decision gets its full budget (PP:199-205). Reported: `plan_timeouts`,
  `plan_timeout_rate`.
* **Memory:** the rollout pool is sized from available memory (30% reserve, 1.5 GB per
  worker, cap 12; SR:3106-3146) and shrinks or stops (MemoryError) if available memory falls
  below the reserve. A memory stop ends the run; the harness records it as a failed job and
  never substitutes results.

## 5. Stated assumptions of the procedure

All of them are also listed in `docs/STATED_ASSUMPTIONS.md`.

1. **Planner world = legacy estimator belief** (user decision 2026-10-16): the rollout world
   is the robots' legacy SESTPP estimates, which differ from the truth in form and units
   (engine residual R14). Plan Eq. 20 is kept: the legacy world forecast does not generate
   future offspring (SR:407-411).
2. **Engine residual differences R1-R14** between the engine's B5 and the real B5
   (`SR.B5_RESIDUAL_DIFFERENCES`, SR:147-193): frozen zones and health, lane-projection
   motion only, same-step event order, cell-expected exposure weights, node-snapped
   offspring kernels in the J integral, planner world in place of truth, unmirrored
   metrics/telemetry, no `predictive_action_variants`, no diagnostic counters, scenario-keyed
   patrol jitter, no preventive-capacity recomputation, candidate-first execution rule,
   planner-model mu EMA only through the estimators, belief snapshots.
3. **16 scenarios with common random numbers** (user decision 2026-10-21 after the
   scenario-count test): J_hat is a Monte Carlo mean, not the planner-model expectation.
4. **Gate**: eps_gate = 0 with a 2-standard-error Monte Carlo significance margin.
5. **No reservation** (final user decision 2026-10-22): no ceiling and no floor in the plan
   variants; the B4 variants keep the B4 floor (rho = 0.25 over 600 s), so C_gate -> C_plan
   changes the reservation (floor -> none) as well as the procedure.
6. **Finite horizon, no terminal cost**: J_H stops at t + H; a pending task not completed by
   t + H has completion time +inf in every comparison (decision 30); the terminal summary
   is logged, not costed.
7. **Deadlines**: d_j = creation + 90 s for every reactive task (no per-task deadlines).
8. **Service protection protects predicted completions only** (Plan Sec. 4): no guarantee
   under unforecast arrivals or travel error; the disturbance study measures F0-protected
   tasks that still missed.
9. **Timed-recovery thresholds** E_high = 323.8, E_low = 29.1, T_response = 300 s are pooled
   over loads from dev seeds 200-209 under B5 (docs/calibration/timed_recovery_thresholds.json);
   a stand-in for physical values (no physical values exist).
10. **Effectiveness floor** 0.4 on planner q_hat at application, any applied scenario.
11. **Sequential commitment**: one deviation per robot per decision, fleet argmax per round;
    no joint optimisation over robots.
12. **Information**: instant full sharing by default; per-robot information sets via the
    information provider (decision 17) with relays as in `docs/communication_assumptions.md`.
13. **No coverage requirement** in D/E (decision 25); A/B keep the original uniform coverage clause.
14. **Oracle** (diagnostic, Section 5 doc): truth snapshot, 64 independent scenarios, every
    candidate of every round on 25% of decisions (confirmed 2026-10-22; measured cost +8% wall
    time, about 0 extra memory).
15. **Ties**: the fleet argmax breaks exact-U ties to the lowest candidate index (PP:787,
    accepted 2026-10-22); the tie count is reported (`plan_exact_u_tie_count`).
16. **Obligations past the horizon** (confirmed 2026-10-22): see the Timed recovery section of
    `docs/section5_analytical_claims.md`.

## 6. Parameters (evaluation values)

| Parameter | Value | Source |
|---|---|---|
| `plan_n_scenarios` | 16 | decision 2026-10-21 |
| `plan_horizon_s` | `forecast_horizon_s` = 300 s | simulator default; accepted by the user 2026-10-22 (STATED_ASSUMPTIONS P6) |
| `reactive_override_slack_s` (deadline) | 90 s | paper config |
| `plan_eps_gate`, `plan_gate_se_multiplier` | 0.0, 2.0 | decision 2026-10-18 |
| `reservation_mode`, `reservation_fraction`, `reservation_window_s` | not set (no reservation) | final user decision 2026-10-22 |
| `plan_compute_budget_s` | 1e9 (none); 45 s in the timeout study | decision 16 |
| `plan_oracle_fraction`, `plan_oracle_scenarios` | 0.25, 64 | decision 31; confirmed 2026-10-22 |
| `plan_oracle_all_candidates` | True (every candidate on the sampled 25%) | decision 12; confirmed 2026-10-22 (+8% wall time, about 0 memory) |
| `plan_protect_late_tasks` | True | accepted by the user 2026-10-22 |
| `plan_obligation_relaxation` | `bounded_violation` | decision 28 |
| `plan_E_high`, `plan_E_low`, `plan_T_response_s` | 323.8, 29.1, 300 s (E_plan_tr) | 2026-10-17 |
| `plan_eta_floor` | 0.4 (E_plan_floor) | decision 26 |
| `plan_valuation` | `continuation`; `one_intervention` (C_plan) | decision 8 |
| `task_replan_period_s` | 45 s | paper config |
