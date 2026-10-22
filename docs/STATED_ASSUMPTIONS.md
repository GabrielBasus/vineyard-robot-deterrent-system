# Stated assumptions (consolidated)

Every modeling or implementation assumption that remains in the evaluated system after the
improvement-plan rebuild, with its source (user decision, plan section, or code location).
Line numbers refer to commit `32c83b9`. "Decision n" = the Section 6 decisions of 2026-10-21
(and follow-ups of 2026-10-22); dated decisions are earlier user decisions. Nothing in this
list was decided by an agent; open items are listed at the end.

## 1. System and environment (kept as in the original system)

| # | Assumption | Source |
|---|---|---|
| S1 | The system keeps its original assumptions: legacy planner estimator (additive `OnlineSESTPP`), paper STL thresholds, paper excitation kernel scaling (sigma 48, omega 1800). The consistent estimator and quantile-mapped thresholds stay in code behind flags and are not evaluated. | user 2026-10-16, 2026-10-15 |
| S2 | Plan Eq. 20: the legacy forecast advances existing excitation by passive decay and generates no future offspring (also in the rollout world, `legacy_future_offspring=False`). | paper Eq. 20; `scenario_rollout.py:401-405`; 2026-10-17 |
| S3 | Partial observability is a stated modeling condition (robots see detections in range; estimators are beliefs). | 2026-10-14 |
| S4 | Evaluation environment PLAN_ENV: coupled exogenous random streams, complete truth deterrence memory with exact pruning (drop an entry when eta*beta*exp(-(t-tau)/omega) < 1e-9), legacy estimator, `stl_forecast_correction=True` (q x beta in candidate, B5 continuation and executed model feedback). Variant A alone keeps the correction off (the submitted B4 exactly). | Plan Sec. 6; 2026-10-19; decision 1; user 2026-10-22 |
| S5 | Paper configuration: 60 x 48 grid, 4 robots, 1800 s runs without warmup, deterrence beta x4, sigma x4, omega x3, kappa 0.50, rho 0.25 over 600 s, replan every 45 s, reactive deadline 90 s. | `run_plan_completion.PAPER_LADDER_ARGV` |
| S6 | Loads: spare 2e-5, heavy 1e-4, overload 4e-4 (paper loads only). | decision 21 |
| S7 | Production habituation recovery T_rec = 1800 s (persistent study uses only this value). | decision 22 |

## 2. Forecast and B4-pipeline variants (A, B, C, C_gate)

| # | Assumption | Source |
|---|---|---|
| F1 | B = all Section 2 items: reactive tasks in the pending timeline mapped to the laser cue (the cue the simulator depletes for direct detections), queue-aware lead, forward trajectory correction, planner update model in forecasts. | decision 5 |
| F2 | Committed-schedule emulation: each robot's own dispatch rule over its committed tasks, no new arrivals, prunings or expiries, straight-line profile speed, idle waits in place, free one step after its last completion, capped at H; the predictive-share decay over the 600 s window is emulated so ceiling-blocked tasks unblock exactly per the rule. | WS-A follow-ups (a), (b); `planner_committed_schedule.py` |
| F3 | delta_a includes travel and service hold time (application = service completion); planner T_rec/kappa are point estimates from the planner field; no cross-cell coupling (gamma = 0). | `docs/section2_assumptions.md` A1-A11 |
| F4 | C = Plan Eq. 3 over all modeled cells (sum w*lambda, pointwise legacy-form cue-footprint suppression, horizon H, B's forecast), one-intervention counterfactual, left Riemann sum on the simulator dt. | decision 6; 5f6645e |
| F5 | C keeps the patrol comparison and its fixed 0.10 margin (C effectively always prefers deterrence; reported). | WS-A follow-up (c) |
| F6 | C_gate = C + the same gate as D (strict U > 0; the Monte Carlo 2 SE rule reduces to U > 0 for deterministic C) + the same reservation ceiling. | decision 7 |
| F7 | Duplicate (re-)evaluations of a candidate within a decision are kept and flagged (binding log, counts, runtime, ranking). | WS-A follow-up (d) |
| F8 | Section 3: soft-min over the production mask (inactive-action hab entries change the argument count), aggregation tree and numerical convention as documented. | decision 27; `docs/section3_masking_diagnosis.md` |
| F9 | A and B keep the original uniform coverage clause; D/E have no coverage requirement. | decision 25 |

## 3. Plan decision procedure (C_plan, D_plan, E_plan, E_plan_tr, E_plan_floor)

| # | Assumption | Source |
|---|---|---|
| P1 | Executed system = B5 plus admitted forced-first deviations; candidates = B5's own (robot, seed, cue) pairs; one deviation per robot per decision; fleet-wide argmax per round; sequential commitment. | 2026-10-14; `plan_procedure.py:1-33` |
| P2 | Engine residual differences R1-R14 between the engine's B5 and the simulator's B5: R1 frozen zones/health; R2 lane-projection motion only; R3 same-step event order; R4 cell-expected exposure weights; R5 node-snapped offspring kernels in the J integral; R6 planner world replaces truth; R7 metrics/telemetry not mirrored; R8 no predictive_action_variants; R9 no diagnostic counters; R10 scenario-keyed patrol jitter; R11 no preventive-capacity recomputation; R12 candidate-first execution rule; R13 planner mu EMA only through the estimators; R14 belief snapshots (planner model error, measured by the oracle). | `scenario_rollout.py:141-187` |
| P3 | Eq. 3 expectation by Monte Carlo with 16 scenarios and common random numbers (action-dependent intensities, detections and tasks). | 2026-10-14; 2026-10-21 (scenario-count test) |
| P4 | Gate: eps_gate = 0 and U_mean > 2 SE over scenarios. | 2026-10-18 |
| P5 | Reservation is a CEILING (predictive only while share < rho = 0.25 and no protectable reactive task is delayed); the share counts patrol time (`Robot.predictive_share`). | 2026-10-14; 2026-10-15 |
| P6 | Finite horizon H = 300 s, no terminal cost; an uncompleted pending task has completion time +inf; a per-scenario terminal summary is logged. | decision 30 |
| P7 | Service protection: F0^s per scenario; a candidate violating any F0^s task in any scenario is infeasible; optional baseline-late condition on; protected-task outcomes reported "at least one scenario" (primary) and "all scenarios". | Plan Sec. 4; WS-B follow-up |
| P8 | C_plan: C's one-intervention Eq. 3 valuation inside the plan procedure, B5 candidates, unc dispatch, fleet view, same gate and ceiling, NO continuation and NO service protection. | decision 8; WS-B follow-up |
| P9 | Timed recovery (Eq. 4) thresholds E_high = 323.8, E_low = 29.1, T_response = 300 s: pooled over loads, p90 / p50 of per-step planner forecast cell exposure under B5 on dev seeds 200-209; stand-in values (no physical values). | 2026-10-15, 2026-10-17, 2026-10-19; `docs/calibration/timed_recovery_thresholds.json` |
| P10 | Eq. 4 relaxation = bounded violation: keep the obligation, minimise the mean-over-scenarios exceedance of E_low at the deadline summed over obligations, lexicographic (min exceedance, then max U), never worse than pi_0. | decision 28; WS-B follow-up |
| P11 | Effectiveness floor 0.4 on planner q_hat at application: reject if below in ANY applied scenario; never-applied candidates exempt. | decision 26; WS-B follow-up |
| P12 | Information: instant full sharing by default; per-robot information sets = the candidate's robot (its estimator, effectiveness record, known tasks; pi_0 per robot; fleet picks best U). | decision 17; WS-B follow-up |
| P13 | Busy robot = at least one active assigned task. | WS-B follow-up |
| P14 | No wall-clock budget in evaluation runs (simulator clock frozen while planning); 45 s budget only in the exploratory timeout study. | 2026-10-15; decision 16 |
| P15 | Oracle = truth snapshot, 64 scenarios from an independent seed stream, sampled on 25% of decisions; it does not measure R1-R12. | decision 31 |

## 4. Communication (decisions 17, 18; `docs/communication_assumptions.md`)

| # | Assumption | Source |
|---|---|---|
| C1 | The estimator relay stays original (lossy: border radius, debounce, weight threshold); effectiveness records relay completely to every robot. | WS-C follow-up |
| C2 | Late records are inserted at their event time (chronological replay); legacy late stamps decay by exp(-(t_now - t)/omega). | WS-C follow-up |
| C3 | Neighbor delay D and drop probability p act on every relayed message; drops use a dedicated coupled stream keyed by message id and recipient (an intervention and its habituation record share a fate). | decision 18 |

## 5. Metrics and statistics

| # | Assumption | Source |
|---|---|---|
| M1 | Reactive miss fraction = 1 - (reactive tasks completed within 90 s of creation) / (reactive tasks generated); unfinished = missed. Double counting tested: none found, denominator kept. | 2026-10-13; decision 11 |
| M2 | Response time: primary creation-to-completion age of completed tasks (mean/p50/p90), secondary bird-event latency; unfinished tasks reported separately (count and overdue at run end). | decisions 9, 10 |
| M3 | Per-window outcomes: tasks attributed by creation time, judged at run end; exposure by event time. | WS-C follow-up |
| M4 | Predeclared noninferiority margin +2 pp on the mean paired miss-fraction difference (E_plan - B5_c). | 2026-10-13 |
| M5 | Confirmatory family: six hypotheses (exposure and service noninferiority at 3 loads, E_plan vs B5_c, hab on), Holm step-down at familywise 0.05; noninferiority by paired bootstrap upper bound on the mean at the hypothesis' Holm level (Wilcoxon supplementary); exposure by two-sided Wilcoxon. | 2026-10-14; decision 24 |
| M6 | Percent effect = mean paired difference / reference mean x 100; bootstrap resamples whole seed pairs; dev seeds 200-209, eval seeds 300-329; 10-seed studies use 300-309 for every system. | Plan Sec. 6; user 2026-10-22 |

## 6. Robustness study designs

| # | Assumption | Source |
|---|---|---|
| R1 | Mismatch: planner kappa 0.50, environment kappa {0.10, 0.25, 0.50, 0.75, 0.90}; heavy; E_plan, B5_c; 10 seeds. | decision 19 |
| R2 | Neighbor histories: one factor at a time, D in {30, 120, 300} s (p = 0), p in {0.1, 0.3, 0.5} (D = 0); heavy; 10 seeds. | decision 18 |
| R3 | Disturbances (the planner is told neither): truth travel speed 20% below nominal; truth background x2 for 300 s starting at a per-seed uniform time in [300, 1200] s drawn from `CoupledRandomStreams(seed).arrival_burst_start_s` (purpose 15, seed only: identical for every system of a seed). | decision 29; user 2026-10-22 |
| R4 | Persistent: 5400 s runs, windows [0, 1800) and [1800, 5400], demand switch at 2700 s (x5 spare->heavy, x0.2 heavy->spare), depleted start = per-cell/cue eta at the end of an 1800 s B5_c run at the same starting load and seed. | decision 22 |
| R5 | Zero habituation: hab off for truth and planner, 3 loads, 30 seeds. | decision 20 |

## 7. Open items (not decided; no default is assumed)

* Section 3 binding-log sampling fraction for the evaluation runs of A and B (decision 27 says
  "sampled decisions"); off unless `--binding-log-fraction` is given.
* Size (loads, seeds) of the exploratory E_plan_tr vs E_plan study; not scheduled unless
  `--tr-loads` and `--tr-seeds` are given.
* Whether the timeout study's reference (E_plan without budget on dev seeds 200-209) is
  wanted; it is scheduled because the "effect" of the budget needs a reference.
