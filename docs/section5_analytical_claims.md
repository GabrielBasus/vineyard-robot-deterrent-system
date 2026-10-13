# Section 5: Algorithm and Achievable Analytical Claims

## Decision Procedure

At each planning step the system executes the following six steps:

1. **Reconstruct local state.** Collect cell exposure estimates, habituation
   levels, pending deterrence events, and reactive task deadlines from the
   current simulation frame.  Freeze one snapshot for the decision.

2. **Generate baseline continuation.** Evaluate J_H(pi_0) under the greedy
   baseline policy (habituated cue rotation with no predictive commitment).

3. **Generate candidates.** For each predictive cell/mode/lead triple, compute
   the forecast followed by the baseline rule on a copied state, using the
   analytic forward predictor.

4. **Reject infeasible candidates.** Discard any candidate that violates the
   service-protection constraint (Plan §4E): if admitting the candidate delays
   a task in F_0 = {j : C_hat_j(pi_0) <= d_j} past its deadline, reject it.
   Discard candidates with U(a) <= benefit_gate.

5. **Select and execute.** Choose the candidate with the highest U(a) =
   J_H(pi_0) - J_H(pi_a).  Execute its first action only if U(a) > gate;
   otherwise fall back to the baseline.

6. **Log and replan.** Record predicted benefit, constraint status, realized
   service metrics, and per-step runtime.  Replan from fresh observations at
   the next task_replan_period_s boundary while preserving existing temporal
   commitments.

## Implementation mapping

| Step | Code location |
|---|---|
| 1 | `DeterrentSystem._stl_pending_events_by_robot`, `_stl_reactive_tasks` |
| 2 | `greedy_rollout(candidate=None)` in `habituation_stl/rollout.py` |
| 3 | `counterfactual_value()` in `habituation_stl/task_value.py` |
| 4 | `service_feasibility()` in `habituation_stl/rollout.py`; benefit_gate check |
| 5 | `TaskGenerator.configure_actions()` → `predictive_selection_policy="utility"` |
| 6 | `run_simulation_frames_persistent()` per-frame metrics logging |

## Proposition 1: Predicted baseline comparison

*At a fixed decision state, suppose the unchanged baseline is in the feasible
candidate set and all candidates are evaluated with the same cost definition and
horizon.  An exact minimizer of (6) satisfies:*

    J_hat_H(pi*) <= J_hat_H(pi_0).

*Proof.* The baseline is an available feasible choice, so the minimum cannot
exceed its evaluated cost.  A positive admission margin (benefit_gate > 0)
preserves this inequality because unsuccessful deviations revert to the
baseline. []

**Implementation note.** The code implements a maximizer of U(a) = J_H(pi_0) -
J_H(pi_a), which is equivalent.  The benefit_gate parameter sets U(a) to 0 when
U(a) <= benefit_gate.

**Correction (2026-10-13).** Setting U(a) to 0 did not by itself withhold the
candidate: under the heuristic preventive gate a zero-score candidate still
became a predictive task, and the "utility" dispatch policy picks the highest
priority predictive task regardless of score.  Variants D and E as run before
this date therefore did not implement the admission step of the decision
procedure.  `stl_strict_admission=True` (TaskGenerator candidate loop) now drops
any candidate with U(a) <= benefit_gate before task creation, so the robot
falls back to the baseline behaviour (reactive service, patrol or idle).  The
counts appear as `predictive_rejected_benefit_gate_total` and
`predictive_passed_benefit_gate_total` in the run metrics.  Proposition 1 holds
only for runs with strict admission on.

**Scope.** This is a design property of the fixed-state decision, not a
closed-loop guarantee.  Repeated replanning, incomplete information, and
concurrent decisions require additional assumptions.

## Proposition 2: Effect of bounded cost-estimation error

*At a fixed decision state, suppose |J_hat_H(pi) - J_H(pi)| <= epsilon for
every evaluated candidate and the baseline, where J_H is the true expected cost
of executing that continuation.  Then a selected candidate satisfies:*

    J_H(pi*) <= J_H(pi_0) + 2*epsilon.

*If J_hat_H(pi_0) - J_hat_H(pi*) > 2*epsilon, its true cost is strictly smaller.*

*Proof.* J_H(pi*) <= J_hat_H(pi*) + epsilon and J_hat_H(pi_0) <= J_H(pi_0) +
epsilon.  Combining gives both statements. []

**Research implication.** The substantive claim is to characterize estimation
error empirically.  The 30-seed evaluation at spare load (Section 6) provides a
first characterization: at mu=2e-5, U(a) is near-zero with high variance across
seeds, suggesting epsilon is large relative to the signal at this load.  The
bound J_H(pi*) <= J_H(pi_0) + 2*epsilon is therefore not tight at spare load.
The evaluation at higher loads (if run) would give a sharper characterization
because habituation pressure amplifies the true benefit signal.

**Validation note.** A validation-set error quantile is not a deterministic
uniform bound.  A guarantee about expected continuation cost is not a guarantee
for each realization or the eventual replanned trajectory.
