# Section 5: Algorithm and achievable analytical claims (plan procedure)

This document states what can be claimed analytically about the plan decision procedure
(`planner_procedure="plan"`, `habituation_stl/plan_procedure.py`; algorithm steps 1-6 with
code locations in `docs/section4_assumptions.md` Section 2), with every assumption explicit.
It replaces the earlier version written for the B4-pipeline rollout (dropped variants D/E).

Notation. At a decision state x_t: pi_0 = the B5 continuation; pi_a = candidate a first, then
B5; H = 300 s (simulator default `forecast_horizon_s`, see docs/STATED_ASSUMPTIONS.md P6); J_H(pi) = expected value-weighted exposure over [t, t + H] under the TRUE
model when executing pi (the engine's mirrored B5, see A2 below); J*_H(pi) = the same
expectation under the PLANNER model (planner world from the robots' estimators);
J_hat(pi) = mean over the n = 16 common-random-number scenarios of the planner model;
U_hat(a) = J_hat(pi_0) - J_hat(pi_a), with paired standard error se(a).

## Assumptions used by the statements

* **A1 (fixed decision state).** Statements are about one decision at one frozen snapshot.
  Nothing is claimed about the closed loop under repeated replanning, incomplete
  information, or concurrent decisions (Plan Sec. 5).
* **A2 (common engine).** pi_0 is the engine's B5, which differs from the simulator's B5 by
  the residuals R1-R14 (`scenario_rollout.B5_RESIDUAL_DIFFERENCES`); "executing pi_0" means
  the engine's continuation. The executed fallback is the simulator's own B5 (identical
  first action by construction of the forced-first deviation).
* **A3 (candidate set).** pi_0 is always available (no candidate is required), and all
  candidates and pi_0 in a round are evaluated with the same horizon, the same cost
  definition and the same scenario trees (common random numbers, same decision seed).
* **A4 (deterministic replay).** Given the snapshot, the policy and the scenario tree, a
  rollout is deterministic (scenario-keyed streams; parallel equals serial, tested in
  tests/test_scenario_rollout.py).
* **A5 (gate).** eps_gate = 0, k = 2: a candidate is admitted only if U_hat(a) > 2 se(a) >= 0.

## Proposition 1 (predicted baseline comparison) -- holds as implemented

*Under A1, A3 and A5, the continuation selected in a round satisfies*
J_hat(pi_selected) <= J_hat(pi_0) *for that round's pi_0, with strict inequality whenever a
deviation is admitted.*

*Proof.* If no candidate passes feasibility and the gate, nothing is injected and the
executed continuation is pi_0. Otherwise the admitted a has U_hat(a) > 2 se(a) >= 0, i.e.
J_hat(pi_a) < J_hat(pi_0). With bounded timed-recovery obligations the lexicographic rule
picks among admissible candidates only (all with U_hat > 0) and prefers pi_0 when every
admissible candidate has a larger exceedance, so the inequality is preserved. []

*Sequential commitment.* Round k + 1 uses the snapshot with round k's deviation committed,
so its pi_0 is the continuation selected in round k evaluated on the same decision seed.
Under A4 the J_hat of that continuation is the same number in both rounds, and the chain
gives J_hat(executed) <= J_hat(pi_0 of round 0). This equality is checkable from the
decision log (`rounds[k+1].J0_mean` vs the admitted candidate's round-k `J_mean`);
it is a property of the implementation, not an additional assumption, but it has not been
asserted by a test.

*Scope.* This is a statement about the planner's Monte Carlo estimate. It says nothing about
J_H, about J*_H (the planner-model expectation), or about the realized exposure.

## Proposition 2 (bounded estimation error) -- conditional

*Assume (A6) |J_hat(pi) - J_H(pi)| <= epsilon for pi_0 and the selected pi_a at the decision
state. Then* J_H(pi_a) <= J_H(pi_0) + 2 epsilon, *and if* U_hat(a) > 2 epsilon *the true
continuation cost is strictly smaller.* (Proof as in Plan Sec. 5.)

The error has two parts, neither assumed small:
1. **Model error** J*_H - J_H: planner world (legacy estimator form and units, detection-
   thinned parents, Eq. 20 no future offspring, nominal planner parameters) vs truth.
2. **Monte Carlo error** J_hat - J*_H: standard error over 16 scenarios. The gate controls
   only this part: if the model error were zero and the 16 paired differences were normal,
   U_hat > 2 se has a one-sided false-admission probability of about 3% per candidate
   (t distribution, 15 degrees of freedom). Taking the argmax over many candidates and
   robots inflates this, so the gate is not a familywise guarantee.

**Empirical characterization (the substantive claim, Plan Sec. 5).** epsilon is measured by
the oracle (below), not assumed. Because the planner world is in legacy estimator units and
the oracle in truth units, the two J scales differ by a variable factor, so the reporting is
split (user decision 2026-10-22, audit round):
* PRIMARY (scale-free): the sign-agreement fraction of U_hat and U_oracle
  (`plan_oracle_U_sign_agree_fraction`); Kendall tau between planner U and oracle U over all
  round-0 candidates of a sampled decision (`plan_oracle_kendall_tau_mean`/`_median`,
  decision 12); the fraction of admitted deviations with U_oracle > 0
  (`plan_oracle_admitted_U_oracle_positive_fraction`).
  The primary metrics are `plan_prop2_{sign_agree_fraction, sign_agree_n, kendall_tau_mean,
  kendall_tau_median, kendall_tau_n, admitted_oracle_U_positive_fraction, admitted_oracle_n}`.
* SECONDARY (raw, unit-mixed, suffix `_raw_units`): bias, mean, 95th percentile and maximum
  of |J0_hat - J0_oracle|, |Ja_hat - Ja_oracle| and |U_hat - U_oracle|
  (`plan_pred_err_{J0,Ja,U}_*_raw_units`), realized minus predicted J of the executed policy
  (`plan_realized_minus_pred_mean[_abs]_raw_units`) and the oracle standard errors
  (`plan_oracle_{J0,U}_se_mean_raw_units`, `plan_oracle_admitted_U_oracle_mean_raw_units`);
  `plan_pred_err_J0_rel_mean` keeps its name.
* C_plan has no continuation: its J-hat is the one-intervention J, compared with the realized
  exposure as `plan_realized_minus_one_intervention_J_{windows, mean_raw_units}`.
* With per-robot information sets: per robot `plan_pr_prop2_<metric>_<rid>` and their mean and
  spread across robots (`plan_pr_prop2_*_robot_{mean, spread_sd}`), plus each robot's own
  J-hat of the executed policy against the realized J
  (`plan_pr_realized_minus_pred_{mean, mean_abs, spread_sd, spread_range}_raw_units`).
Calibration on dev seeds (2026-10-18) found sign agreement 88-89%, 90% of admitted
deviations truly beneficial, and corr(U_hat, U_oracle) near 0 because the legacy units are
off by a variable factor. An error quantile from these runs is a validation statistic, not a
deterministic uniform bound, and a bound on expected continuation cost is not a bound on any
single realization or on the replanned trajectory.

## The oracle (definition)

For a sampled fraction (0.25, independent stream) of decisions, after the decision is made
and outside its runtime budget (`PlanProcedure._oracle`):
* **World:** the truth snapshot, `decision_snapshot_from_sim_locals(..., oracle=True)`: truth
  background, excitation, suppression store, truth cue parameters and truth habituation
  (`truth_forecast_from_sim_locals`, `truth_world_cues`). The policy side (robots, tasks,
  estimators, planner habituation used by B5's decisions) is unchanged, so the oracle
  evaluates the SAME policies the planner evaluated, in the true world.
* **Scenarios:** 64, drawn from a seed stream independent of the planner's
  (SeedSequence [seed, 0x0AC1E5, decision index]; decision 31); oracle Monte Carlo standard
  errors are reported (`plan_oracle_J0_se_mean`, `plan_oracle_U_se_mean`).
* **Policies:** with `plan_oracle_all_candidates=True` (the evaluation setting), every
  candidate of every round together with that round's pi_0 (with the earlier rounds'
  commitments), on 25% of decisions with 64 scenarios (confirmed 2026-10-22; it supersedes
  "top candidate only"). Measured cost: +8% wall time, about 0 extra memory
  (`plan_oracle_decisions`, `plan_oracle_wall_s_total`).
* **What it measures:** model error plus planner Monte Carlo error relative to the truth
  model under the engine's B5. It does NOT measure the engine residuals R1-R12 (shared by
  planner and oracle); those were bounded separately by the engine-vs-simulator agreement
  test (mean B5 exposure within 0.2%).

## Service protection (Plan Sec. 4): what is and is not guaranteed

*Conditional statement.* If a deviation is admitted under service protection then, in every
one of the 16 planner scenarios, every pending task predicted on time under pi_0 is predicted
on time under the deviation, and (`plan_protect_late_tasks=True`, accepted by the user
2026-10-22) no baseline-late task with finite
completion finishes later. This is a property of the planner model's scenarios only:
* no guarantee for unforecast arrivals, travel-speed error or scenarios not sampled (the
  disturbance study reports F0-protected tasks that still missed, both "at least one
  scenario" (primary) and "all scenarios");
* tasks created after t are not protected (they are not pending);
* the horizon covers every pending deadline (asserted at each decision), so no protected
  deadline is censored by the horizon.

## Timed recovery (Plan Eq. 4)

**Live monitor** (simulator, every step; user decisions 2026-10-22, "as implemented"): the
monitored unit z is a robot zone (`L["cells"]` partition polygon); e_z = sum over the zone's
grid nodes of w * lambda_hat under the planner forecast (the same world the rollouts use). An
obligation is triggered when e_z > E_high and the zone has no active obligation and is not
latched; it is discharged when e_z <= E_low by its deadline (trigger + T_response) and
violated at the first step after the deadline otherwise (violation size = last e_z before the
deadline minus E_low). After a violation the zone is LATCHED: no new obligation until e_z has
recovered to <= E_low. The live monitor always judges at the REAL deadline.

**Inside a decision.** Feasibility is per-scenario dominance: a candidate must satisfy, in
each scenario, every obligation pi_0 satisfies there (accepted 2026-10-22). Obligations that
no feasible policy satisfies in every scenario are kept as bounded violations; the set of
bounded obligations is fixed in round 0 of the decision (accepted 2026-10-22). The choice
minimises the mean-over-scenarios exceedance of E_low summed over them and never prefers a
policy with a larger exceedance than pi_0 (decision 28).

**Deadlines beyond the look-ahead** (confirmed 2026-10-22): an obligation whose deadline lies
after t0 + H and that is unmet at t0 + H stays OPEN (it is neither satisfied nor violated
inside the decision). When neither pi_0 nor the candidate meets it by t0 + H, the candidate
must not leave a higher e_z at t0 + H than pi_0 (else `infeasible_obligation`), and the
bounded-violation size is the exceedance of E_low at t0 + H (logged as a horizon proxy). The
live monitor still judges the obligation at its real deadline. No global deadline guarantee
follows (Plan Sec. 7); violations and their sizes are reported.

## Claims that are NOT made

Global deadline guarantees, closed-loop improvement over B5, universal superiority to greedy
dispatch, optimality of the selected deviation over all policies (the candidate set is B5's
own seeds x cues, one deviation per robot per decision), species-specific effectiveness,
decentralized scalability. These require evidence beyond the first implementation (Plan Sec. 7).
