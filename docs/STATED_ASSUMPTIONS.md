# Stated assumptions (consolidated)

Every modeling or implementation assumption that remains in the evaluated system after the
improvement-plan rebuild, with its source (user decision, plan section, or code location).
Line numbers refer to commit `704722c` unless marked (updated 2026-10-22; the reconciled
branch is `e3ec247`). "Decision n" = the Section 6
decisions of 2026-10-21 (and follow-ups and audit rounds of 2026-10-22); dated decisions are
earlier user decisions; "accepted 2026-10-22" = an implemented behavior the user reviewed and
accepted in the 2026-10-22 audit round. Nothing in this list was decided by an agent; open
items are listed at the end. All decided simulator items are implemented at `e3ec247`.

## 1. System and environment (kept as in the original system)

| # | Assumption | Source |
|---|---|---|
| S1 | The system keeps its original assumptions: legacy planner estimator (additive `OnlineSESTPP`), paper STL thresholds, paper excitation kernel scaling (sigma 48, omega 1800). The consistent estimator and quantile-mapped thresholds stay in code behind flags and are not evaluated. | user 2026-10-16, 2026-10-15 |
| S2 | Paper Eq. 20 (the ACC paper's Eq. 20): the legacy forecast advances existing excitation by passive decay and generates no future offspring (also in the rollout world, `legacy_future_offspring=False`). | paper Eq. 20; `scenario_rollout.py:407-411`; 2026-10-17 |
| S3 | Partial observability is a stated modeling condition (robots see detections in range; estimators are beliefs). | 2026-10-14 |
| S4 | Evaluation environment PLAN_ENV: coupled exogenous random streams, complete truth deterrence memory with exact pruning (drop an entry when eta*beta*exp(-(t-tau)/omega) < 1e-9), legacy estimator, `stl_forecast_correction=True` (q x beta in candidate, B5 continuation and executed model feedback). Variant A alone keeps the correction off (the submitted B4 exactly). | Plan Sec. 6; 2026-10-19; decision 1; user 2026-10-22 |
| S5 | Paper configuration: 60 x 48 grid, 4 robots, 1800 s runs without warmup, deterrence beta x4, sigma x4, omega x3, kappa 0.50, rho 0.25 over 600 s, replan every 45 s, reactive deadline 90 s. | `run_plan_completion.PAPER_LADDER_ARGV` |
| S6 | Loads: spare 2e-5, heavy 1e-4, overload 4e-4 (paper loads only). | decision 21 |
| S7 | Production habituation recovery T_rec = 1800 s (persistent study uses only this value). | decision 22 |
| S8 | Reservation: NO ceiling anywhere. The B4-based variants A, B, C, C_gate keep the submitted B4 reservation FLOOR, rho = 0.25 over 600 s (`reservation_mode="floor"`: predictive work first while the predictive share < rho, after reactive work at any share; the share counts patrol time, `Robot.predictive_share`). The B5-based plan variants C_plan, D_plan, E_plan, E_plan_tr, E_plan_floor have NO reservation (no reservation parameter; `unc` dispatch). Consequently the step C_gate -> C_plan changes the reservation too (floor -> none), in addition to the plan procedure (B5 candidates, `unc` dispatch, fleet view). | final user decision 2026-10-22 |

## 2. Forecast and B4-pipeline variants (A, B, C, C_gate)

| # | Assumption | Source |
|---|---|---|
| F1 | B = all Section 2 items: reactive tasks in the pending timeline mapped to the laser cue (the cue the simulator depletes for direct detections), queue-aware lead, forward trajectory correction, planner update model in forecasts. | decision 5 |
| F2 | Committed-schedule emulation: each robot's own dispatch rule over its committed tasks, no new arrivals, prunings or expiries, straight-line profile speed, idle waits in place, free one step after its last completion, capped at H; the predictive-share decay over the 600 s window is emulated so the share-dependent reservation rule (the floor) is applied exactly as in the simulator. | WS-A follow-ups (a), (b); `planner_committed_schedule.py` |
| F3 | delta_a includes travel and service hold time (application = service completion); planner T_rec/kappa are point estimates from the planner field; no cross-cell coupling (gamma = 0). | `docs/section2_assumptions.md` A1-A11 |
| F4 | C = Plan Eq. 3 over ALL modeled cells (sum w*lambda, pointwise legacy-form cue-footprint suppression, horizon H, B's forecast), one-intervention counterfactual, left Riemann sum on the simulator dt. | decision 6; user 2026-10-22 (audit); 5f6645e |
| F5 | C keeps the patrol comparison and its fixed 0.10 margin (C effectively always prefers deterrence; reported). | WS-A follow-up (c) |
| F6 | C_gate = C + the same gate as D (strict U > 0; the Monte Carlo 2 SE rule reduces to U > 0 for deterministic C), with the same reservation floor as C (no ceiling). | decision 7; user 2026-10-22 (audit) |
| F7 | Duplicate (re-)evaluations of a candidate within a decision are kept and flagged (binding log, counts, runtime, ranking). | WS-A follow-up (d) |
| F8 | Section 3: soft-min over the production mask (inactive-action hab entries change the argument count), aggregation tree and numerical convention as documented. | decision 27; `docs/section3_masking_diagnosis.md` |
| F9 | A and B keep the original uniform coverage clause; D/E have no coverage requirement. | decision 25 |
| F10 | Dual same-state shadows: (a) forecast-only (`stl_shadow_overrides`: A re-scored with `forecast_correction` True, B with it False) and (b) full Section 2 set, inputs included (`stl_shadow_full_section2`: A re-scored with all five Section 2 flags True, i.e. as B; B with all five False, i.e. as A). Reported as `stl_shadow_forecast_*` and `stl_shadow_full_*` (top-1 agreement, Kendall tau, masked fraction, compared groups; each also `_first_eval`, without re-evaluations); the legacy `stl_shadow_*` names equal the forecast-only shadow. The full-set shadow of A equals B's primary score on the same state (tested in the simulator workstream). | decision 12; user 2026-10-22 (audit, RE-ASKED; confirmed) |
| F11 | Queue-aware lead: a robot not free within H has lead +inf, so the candidate has zero value. | accepted 2026-10-22; `planner_committed_schedule.py:43-44` |

## 3. Plan decision procedure (C_plan, D_plan, E_plan, E_plan_tr, E_plan_floor)

| # | Assumption | Source |
|---|---|---|
| P1 | Executed system = B5 plus admitted forced-first deviations; candidates = B5's own (robot, seed, cue) pairs; one deviation per robot per decision; fleet-wide argmax per round; sequential commitment. | 2026-10-14; `plan_procedure.py:1-33` |
| P2 | Engine residual differences R1-R14 between the engine's B5 and the simulator's B5: R1 frozen zones/health; R2 lane-projection motion only; R3 same-step event order; R4 cell-expected exposure weights; R5 node-snapped offspring kernels in the J integral; R6 planner world replaces truth; R7 metrics/telemetry not mirrored; R8 no predictive_action_variants; R9 no diagnostic counters; R10 scenario-keyed patrol jitter; R11 no preventive-capacity recomputation; R12 candidate-first execution rule; R13 planner mu EMA only through the estimators; R14 belief snapshots (planner model error, measured by the oracle). | `scenario_rollout.py:147-193` |
| P3 | Eq. 3 expectation by Monte Carlo with 16 scenarios and common random numbers (action-dependent intensities, detections and tasks). | 2026-10-14; 2026-10-21 (scenario-count test) |
| P4 | Gate: eps_gate = 0 and U_mean > 2 SE over scenarios. | 2026-10-18 |
| P5 | Reservation: NONE in the plan variants (no ceiling, no floor); the predictive share is still logged with every decision. The B4 variants keep the floor (S8). | final user decision 2026-10-22 |
| P6 | Finite horizon H = 300 s, no terminal cost; an uncompleted pending task has completion time +inf; a per-scenario terminal summary is logged. H is the simulator default `forecast_horizon_s=300.0` (`DeterrentSystem.py:2613`, present since c74a629, 2026-03-30; `plan_horizon_s=None` falls back to it), equal to the ladder's B4 STL horizon (`--stl-horizon-s` 300, `run_habituation_stl_production_ladder.py:1069`); the ACC paper does not state H. H = 300 s accepted by the user 2026-10-22. | decision 30 (terminal); H accepted 2026-10-22 |
| P7 | Service protection: F0^s per scenario; a candidate violating any F0^s task in any scenario is infeasible; protect late tasks ON (`plan_protect_late_tasks=True`: a baseline-late task with finite completion must not finish later than under pi_0); protected-task outcomes reported "at least one scenario" (primary) and "all scenarios". | Plan Sec. 4; WS-B follow-up; protect late tasks accepted by the user 2026-10-22 |
| P8 | C_plan: C's one-intervention Eq. 3 valuation inside the plan procedure, B5 candidates, unc dispatch, fleet view, same gate, NO reservation (S8), NO continuation and NO service protection. Its J-hat is the one-intervention J (its Prop. 2 comparison is `plan_realized_minus_one_intervention_J_*`). Final parameters: PLAN_ENV + the plan settings + `plan_service_protection=False`, `plan_valuation="one_intervention"`. | decision 8; WS-B follow-up; user 2026-10-22 |
| P9 | Timed recovery (Eq. 4) thresholds E_high = 323.8, E_low = 29.1, T_response = 300 s: pooled over loads, p90 / p50 of per-step planner forecast cell exposure under B5 on dev seeds 200-209; stand-in values (no physical values). | 2026-10-15, 2026-10-17, 2026-10-19; `docs/calibration/timed_recovery_thresholds.json` |
| P10 | Eq. 4 inside a decision: per-scenario dominance (a candidate must satisfy, in each scenario, every obligation pi_0 satisfies there); relaxation = bounded violation with the bounded set FIXED in round 0: keep the obligation, minimise the mean-over-scenarios exceedance of E_low summed over obligations, lexicographic (min exceedance, then max U), never worse than pi_0. | decision 28; WS-B follow-up; dominance and round-0 relaxation accepted 2026-10-22 |
| P11 | Effectiveness floor 0.4 on planner q_hat at application: reject if below in ANY applied scenario; never-applied candidates exempt. | decision 26; WS-B follow-up |
| P12 | Information: instant full sharing by default; per-robot information sets = the candidate's robot (its estimator, effectiveness record, known tasks; pi_0 per robot; fleet picks best U). r simulates the whole fleet with its own beliefs: every robot's estimator and cue effectiveness in r's rollouts are r's, and the B5-facing action record is the one r knows; poses, goals and tasks stay the centralized task state. Prop. 2 is reported per robot (each robot's own J-hat of the executed policy vs realized J; per-robot errors, their mean and spread across robots). Installed automatically by `planner_hab_mode="per_robot"`. | decision 17; WS-B follow-up; user 2026-10-22 (Q3, Q4) |
| P13 | Busy robot = at least one active assigned task. | WS-B follow-up |
| P14 | No wall-clock budget in evaluation runs (simulator clock frozen while planning); 45 s budget only in the exploratory timeout study. Timeouts are never a reason to drop a run: in the timeout study they are an outcome (`plan_timeout_rate`, `plan_rejected_timeout`). | 2026-10-15; decision 16; user 2026-10-22 |
| P15 | Oracle = truth snapshot, 64 scenarios from an independent seed stream, on 25% of decisions, evaluating EVERY candidate of EVERY round (and pi_0 of each round). Measured cost: +8% wall time, about 0 extra memory. It does not measure R1-R12. Reported: `plan_oracle_decisions`, `plan_oracle_wall_s_total`. | decision 31; decision 12; confirmed 2026-10-22 (supersedes "top candidate only") |
| P16 | C_plan application time: the candidate's own robot travels and holds under the engine's motion model from the snapshot (a hold in progress finishes first), the same time in every scenario. | user 2026-10-22 (Q1) |
| P17 | Fleet argmax ties: exact-U ties go to the lowest candidate index (`plan_procedure.py:787`); the count of exact-U ties is reported (`plan_exact_u_tie_count`). | accepted 2026-10-22 |
| P18 | E_plan_tr exposure monitor (every simulator step): monitored unit = robot zone (partition polygon `L["cells"]`); e_z = sum over the zone's grid nodes of w * lambda_hat under the PLANNER forecast; trigger when e_z > E_high with no active obligation and the zone not latched; discharged when e_z <= E_low by trigger + T_response; violated at the first step after the deadline (size = last e_z before the deadline minus E_low); after a violation the zone is LATCHED until e_z has recovered to <= E_low. The live monitor judges at the real deadline. | user 2026-10-22 (RE-ASKED, as implemented); `plan_procedure.py:468-529` |
| P19 | Obligations past the horizon: an obligation with deadline > t0 + H unmet at t0 + H stays OPEN; when neither pi_0 nor the candidate meets it by t0 + H, the candidate must not leave a higher e_z at t0 + H than pi_0 (else `infeasible_obligation`); the bounded-violation size is the exceedance of E_low at t0 + H (logged as a horizon proxy); the live monitor judges at the real deadline. | confirmed 2026-10-22 |

## 4. Communication (decisions 17, 18; `docs/communication_assumptions.md`)

| # | Assumption | Source |
|---|---|---|
| C1 | The estimator relay stays original (lossy: border radius, debounce, weight threshold); effectiveness records relay completely to every robot. | WS-C follow-up (former Q1) |
| C2 | Late records are inserted at their event time (chronological replay); legacy late stamps decay by exp(-(t_now - t)/omega). | WS-C follow-up (former Q2) |
| C3 | Neighbor delay D and drop probability p act on every relayed message; drops use a dedicated coupled stream keyed by message id and recipient (an intervention and its habituation record share a fate). Message ids are drawn only for records that are actually relayed, so a record the relay rule does not send draws nothing. | decision 18; user 2026-10-22 |
| C5 | Per-robot belief about another robot's detections (`Robot.recent_events`, B5's detection-cluster seeds): r's belief of q's detections = q's in-zone detections relayed to r under the estimator relay rule (border radius, partition neighbours only, delay, drop). | user 2026-10-22 (RE-ASKED; former Q3) |
| C6 | B4 keeps central visibility of tasks and estimators in per_robot mode; only cue effectiveness is per robot. | user 2026-10-22 |

## 5. Metrics and statistics

| # | Assumption | Source |
|---|---|---|
| M1 | Reactive miss fraction = 1 - (reactive tasks completed within 90 s of creation) / (reactive tasks generated); unfinished = missed. Double counting tested: none found, denominator kept. | 2026-10-13; decision 11 |
| M2 | Response time: primary creation-to-completion age of completed tasks (mean/p50/p90), secondary bird-event latency; unfinished tasks reported separately (count and overdue at run end). | decisions 9, 10 |
| M3 | Per-window outcomes: tasks attributed by creation time, judged at run end; exposure by event time. | WS-C follow-up |
| M4 | Predeclared noninferiority margin +2 pp on the mean paired miss-fraction difference (E_plan - B5_c). | 2026-10-13 |
| M5 | Confirmatory family: six hypotheses, E_plan vs B5_c, hab on, 3 loads: H1 EXPOSURE by a two-sided Wilcoxon signed-rank test (a superiority test, NOT a noninferiority test) and H2 SERVICE noninferiority by the paired percentile-bootstrap upper bound on the mean at the hypothesis' Holm level (one-sided Wilcoxon on diff - 0.02 supplementary). Holm step-down at familywise 0.05; the hypotheses are ORDERED by p (Wilcoxon p for H1, one-sided bootstrap p for H2 with B = 10000 resamples, seed 12345, percentile method). | 2026-10-14; decision 24; Holm ordering by bootstrap p accepted 2026-10-22 |
| M6 | Percent effect = mean paired difference / reference mean x 100; bootstrap resamples whole seed pairs; dev seeds 200-209, eval seeds 300-329; 10-seed studies use 300-309 for every system. | Plan Sec. 6; user 2026-10-22 |
| M7 | Prop. 2: scale-free metrics PRIMARY (`plan_prop2_*`: planner vs oracle sign agreement of U, Kendall tau of planner vs oracle U over the candidates, fraction of admitted deviations with oracle U > 0, with their counts; per robot `plan_pr_prop2_*`); raw unit-mixed errors SECONDARY (suffix `_raw_units`: `plan_pred_err_{J0,Ja,U}_*`, `plan_realized_minus_pred_*`, `plan_oracle_{J0,U}_se_mean`, `plan_oracle_admitted_U_oracle_mean`; `plan_pred_err_J0_rel_mean` keeps its name). C_plan's J-hat is the one-intervention J (`plan_realized_minus_one_intervention_J_{windows,mean_raw_units}`). | user 2026-10-22 (audit; final) |
| M8 | Missing seeds and undefined values: every analysis (confirmatory and exploratory) ERRORS if a planned seed of a compared system is missing or has a non-finite value in ANY reported metric (a metric is compared when both systems report it, i.e. have a finite value in at least one run); dropping pairs needs an explicit flag (`--allow-missing`) and the dropped seeds and reasons are then listed. Every raw result records its git commit, dirty flag and uncommitted-diff hash; analyses refuse to compare runs from different code (`--allow-mixed-commits` overrides). The runner retries a failed run (`--retries`, default 1) and writes a failure report with the log tail. | user 2026-10-22 (confirmed; final: all metrics) |
| M9 | Exposure vs service trade-off per load: exposure as % of B5_c (100 + percent effect) against the paired miss-fraction difference (pp), 95% bootstrap CIs (`tradeoff.csv/.md/.png`). | user 2026-10-22 (audit) |

## 6. Robustness study designs

| # | Assumption | Source |
|---|---|---|
| R1 | Mismatch: planner kappa 0.50, environment kappa {0.10, 0.25, 0.50, 0.75, 0.90}; heavy; E_plan, B5_c; 10 seeds. The kappa 0.50 cell reuses confirmatory heavy seeds 300-309 (identical effective parameters). | decision 19; user 2026-10-22 |
| R2 | Neighbor histories: one factor at a time, D in {30, 120, 300} s (p = 0), p in {0.1, 0.3, 0.5} (D = 0); heavy; 10 seeds; plus a per_robot REFERENCE cell with D = 0, p = 0 (B5_c and E_plan, seeds 300-309). Each delay/drop cell is compared with the reference: E_plan vs E_plan@ref, B5_c vs B5_c@ref, and (E_plan - B5_c) minus the reference difference. Per-robot Prop. 2 metrics (`plan_pr_*`) are reported. | decision 18; user 2026-10-22 (audit) |
| R3 | Disturbances (the planner is told neither): truth travel speed 20% below nominal; truth background x2 for 300 s starting at a per-seed uniform time in [300, 1200] s drawn from `CoupledRandomStreams(seed).arrival_burst_start_s` (purpose 15, seed only: identical for every system of a seed). The planner's world and rollouts keep the nominal background and speed; the oracle evaluates the truth, so its world includes the burst (and any demand step) and its truth motion is slower by `travel_speed_error` (planner ETAs inside the oracle stay nominal, as in the simulator). The burst desynchronizes the background stream between the disturbed and the nominal run of a seed after the burst (the disturbed-vs-nominal comparison is not draw-for-draw coupled after it); within the burst cell, the pairs (B5_c and E_plan of a seed) stay coupled. | decision 29; user 2026-10-22 |
| R4 | Persistent (the ONE design, `run_plan_studies --study persistent`; `run_persistent_operation.py` refuses to run): 5400 s runs, windows [0, 1800) and [1800, 5400], demand switch at 2700 s (x5 spare->heavy, x0.2 heavy->spare); depleted start = TRUTH eta at the end of an 1800 s B5_c run at the same starting load and seed (truth from truth); the PLANNER always starts fresh (eta = 1) for every system (E_plan, D_plan, B5_c), no informed-planner reference. Thesis wording for the fresh vs depleted difference: "startup after unrecorded prior use". | decision 22; user 2026-10-22 |
| R5 | Zero habituation: hab off for truth and planner, 3 loads, 10 seeds (300-309; reduced from 30 for the budget). | decision 20; user 2026-10-22 |
| R6 | Timed recovery (exploratory): E_plan_tr vs confirmatory E_plan, 3 loads, seeds 300-309. | decision 2; user 2026-10-22 |
| R7 | Timeout: E_plan with a 45 s budget vs E_plan without budget, heavy, dev seeds 200-209, run IN ISOLATION: both cells after every other job, one run at a time with nothing else running. | decision 16; user 2026-10-22 (audit) |
| R8 | Pre-evaluation traces: heavy, dev seed 200, A and B with the binding log of every decision and E_plan with its plan decision log, run BEFORE the evaluation, then `experiments/export_candidate_traces.py` (a few decisions of each kind). | decision 32; user 2026-10-22 (audit) |

## 7. Execution conditions

* Section 3 binding log: every decision of A and B in the confirmatory study (fraction 1.0,
  user decision 2026-10-22). Measured: about 0.59 MB per 300 s heavy run (A and B) and
  2.2 MB per 600 s overload run (A); projected about 1-2 GB for 30 seeds x 3 loads x {A, B},
  so plain JSONL is kept.
* `--study all` overlaps ordinary simulations with the two concurrent plan runs (user decision
  2026-10-22): plan decision runtimes are measured on a loaded machine, not an idle one. The
  trace study runs first; the timeout study runs last, isolated (R7).
* Compute estimate: `py -3.10 -m experiments.run_plan_studies --study all --estimate`
  (run counts per study and load; wall hours from measured per-run rates in two scenarios,
  12-worker rollout pools and 2-worker pools, both with the oracle's +8%).

## 8. Unsupported combinations (clear errors)

| # | Combination | Source |
|---|---|---|
| U1 | Per-robot information sets (`planner_hab_mode="per_robot"` with `planner_procedure="plan"`) together with timed recovery (E_plan_tr thresholds): the obligation ledger and bounded-violation comparison are fleet-level while pi_0 is per robot. `PlanProcedure` raises ValueError. | user 2026-10-22 (Q5) |
| U2 | Per-robot information sets with `estimator_mode="consistent"`: the simulator raises ValueError at start. | user 2026-10-22 (Q5) |
| U3 | C_plan (`plan_valuation="one_intervention"`) with service protection, timed recovery or the effectiveness floor (all need continuation rollouts): `PlanConfig.validate` raises ValueError. | decision 8; WS-B follow-up |

## 9. Accepted as implemented (user, 2026-10-22)

* Protect late tasks (P7).
* Obligation per-scenario dominance with the relaxation (bounded set) fixed in round 0 (P10).
* Timed-recovery monitor latched until recovered, over the robot zone, on planner-forecast
  exposure (P18).
* Oracle on 25% of decisions (P15).
* Fleet argmax ties to the lowest index, tie count logged (P17).
* Queue-aware lead infinite when the robot is not free within H (F11).
* Committed-schedule emulation calls the dispatch rule with a fixed generator rng(0).
* Shared-mode legacy planner world: fleet mean of the robots' estimates at nodes outside every
  robot zone (`scenario_rollout.py`, "unowned nodes: fleet mean"), and the first model's omega.
* Holm ordering by bootstrap p (M5); H = 300 s (P6).

## 10. Open items

* Eq. 4 against TRUE exposure: timed recovery is judged on planner-forecast exposure (P18); its
  satisfaction against the true exposure is currently not reported. It could be added as a
  parallel diagnostic ledger (not implemented; for the user to decide).
* Unsupported combinations U1 and U2 (per_robot + timed recovery, per_robot + consistent
  estimator) remain unsupported by decision; they are not evaluated.
* Section 7: the ACC tag (recommended commit `fec8cf3`) is still to be created after
  verification.
