# B4_mission scope, November 6, 2026

This isolated profile follows the STL thesis proposal's dispatcher contract.
It derives from frozen B4 and enables the fourth reactive-deadline clause for
predictive deterrence valuation. The existing reserved-capacity dispatcher,
reservation share, reactive priority, and hard urgent-reactive override remain
in control; only the choice among already admitted predictive deterrence tasks
is re-ranked by counterfactual mission robustness. Reactive and patrol tasks
are not candidates for this STL selector.

## Retained proposal behavior

- The selected predictive task maximizes full mission robustness relative to
  the common reference queue. The four active clauses are value-weighted
  exposure, reactive service deadline, coverage recency, and the effectiveness
  floor. Smooth/hard aggregation, per-clause normalization, and the B4
  thresholds are retained.
- A reactive task keeps its original creation time and the actual service
  deadline. The `stl_T_react_s` default resolves to
  `reactive_service_deadline_s`; it is not the shorter urgent-override window.
- A candidate is inserted first in the deciding robot's pending schedule.
  Other robots' assigned queues remain fixed and participate in the reactive
  clause. The reference keeps the current task first, then FIFO; queue tails
  use original creation time and stable task id.
- Forecast state is planner-only: estimated exposure, reconstructed planner
  effectiveness, task assignments, fleet poses, effective goals, and service
  holds. No truth events, truth intensity/effectiveness, or future arrivals
  are read. The estimate retains B4's passive exposure decay and target-zone
  suppression approximation; candidate effectiveness is frozen at its
  planning-time estimate.
- Patrol tasks have no deterrence suppression, effectiveness, or service-age
  reset in the forecast. Holds are not interrupted, and no new random draws
  are introduced.
- Candidate and reference use the same time samples, including monitor times
  and modeled completion/deadline events. A current predictive task wins ties;
  otherwise predictive candidates are ranked deterministically.
- The STL selector runs only after the existing dispatcher selects predictive
  work. It cannot change a reactive selection, the urgent override, or whether
  reservation/opportunistic logic permits predictive work.

## Scope and limitations

This profile does not alter candidate generation/admission, assignment,
available cue choices, physics, observations, truth, estimator, habituation
updates, task expiration, or completion rules. It does not enable forecast
correction, sampled B5 continuation, integrated-exposure valuation, graph
motion, aerial spin-up, or a new task-generation model. Its queue and travel
forecast are finite approximations; they do not model unknown future
detections, offspring, or estimation error. These are soft, model-based
priorities rather than guaranteed satisfaction or hard feasibility filters.

The original all-stream selector remains a separate opt-in mode and is not
enabled by `B4_mission`.

## Audit requirements

Test original-deadline preservation, predictive-only candidate filtering,
reactive displacement in the mission score, horizon censoring, coverage
updates, effectiveness penalties, patrol semantics, common sampling, hold
preservation, deterministic ties, absence of input mutation, and
source/configuration isolation. Verify that reservation and hard urgent
reactive dispatch remain active. Compare B1/B4/B5 defaults with the pinned
parent in separate processes on deterministic fixtures. No 90-run evaluation
is launched merely by implementing this variant.
