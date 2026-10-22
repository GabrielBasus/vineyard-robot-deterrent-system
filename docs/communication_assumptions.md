# Communication assumptions (Plan Sec. 6, "communication assumptions"; decisions 17-18)

This file states which information each robot holds in the simulator, for the
two planner effectiveness modes (`planner_hab_mode`), and how neighbor messages
can be delayed or lost (`neighbor_delay_s`, `neighbor_drop_prob`). Defaults
(`"shared"`, 0 s, 0) reproduce the historical simulator bit for bit
(tests/test_estimator_consistent.py::LegacyUnchanged).

## 1. Messages on the EventBus

| Message | Sender | Recipients | Content |
| --- | --- | --- | --- |
| Detection (legacy estimator) | zone owner that detected the bird | each partition neighbor, only if the detection lies within `border_radius_m` of the sender's zone edge (`Robot.ingest_detection`) | x, y, t, weight 0.35, sigma, omega |
| Detection (consistent estimator) | zone owner | every robot whose STL local cells (own zone + partition neighbors) lie within 3 sigma of the detection (`EventBus.publish_detection`) | x, y, t |
| Intervention (legacy estimator) | executing robot | each partition neighbor, only if the action lies within `border_radius_m` of the sender's zone edge, after debounce (`intervention_boundary_min_interval_s` = 60 s per sender/recipient/20 m cell/cue/action) and `intervention_boundary_min_weight` = 0.35 | x, y, t, amplitude, sigma, omega, cue, action id |
| Intervention (consistent estimator) | executing robot | every robot whose STL local cells lie within 3 sigma of the action (`EventBus.broadcast_intervention`) | x, y, t, amplitude q_hat*beta, sigma, omega, cue, action id |
| Habituation record (`planner_hab_mode="per_robot"` only) | executing robot | every other robot (complete relay, `EventBus.relay_habituation`) | t, habituation cell z, cue c, action id |
| Intervention record (`planner_hab_mode="per_robot"` only) | executing robot | every other robot (complete relay, `EventBus.relay_intervention_record`; same message id as the habituation record) | x, y, t, cue, source, action id, habituation cue |

The intensity-model relays (rows 1-4) are the historical rules and are not
changed. The habituation record (row 5) is relayed to every robot, because a
robot may need eta for any cell (the plan procedure's rollout covers the whole
field), and because decision 17 requires instant full sharing to reproduce the
shared field exactly. The two rules stay different by user decision (WS-C
follow-up, 2026-10-22; former question Q1): the estimator relay stays the
original lossy rule while the effectiveness records relay completely.

## 2. Delay and loss (decision 18)

Every message in the table above that goes to a robot other than its sender
passes through `EventBus._relay`:

* Drop draws are made only for messages that are actually sent (a message the
  relay rule does not send draws nothing; user decision 2026-10-22), so the
  drop stream of one message never depends on how many other messages were
  considered.
* Drop: the message to recipient r is lost if `u < neighbor_drop_prob`, where
  `u = CoupledRandomStreams(seed).relay_uniform(kind, message id, r)` (purpose
  code `PURPOSE_RELAY` = 14). The message id is the truth event id for a
  detection (coupled streams) or the action (task) id for an intervention;
  without one, a bus sequence number is used. Because the intervention message
  and its habituation record share the id, they are lost together.
* Delay: a message that is not lost is delivered `neighbor_delay_s` after its
  event time. `EventBus.deliver_due(t)` runs at every step right after the
  habituation recovery (and at every warmup step), so delivery happens at the
  first step time >= event time + D.
* A sender's own observations and completions are never delayed or dropped.
* A delayed message is incorporated at its own event time:
  * consistent estimator: the existing late-stamp decay (`_lag_decay`);
  * legacy estimator: the stamp is multiplied by `exp(-(t_now - t)/omega)` of the
    receiving grid (`OnlineSESTPP._legacy_late_decay`), i.e. the mass the event
    would hold had it arrived on time. Only delayed deliveries pass `t`; all
    historical calls are unchanged;
  * per-robot habituation: chronological reconstruction (section 3).
* Messages still in transit at run end are reported as `relay_pending_at_end`.

Counters: `relay_{detection,intervention,habituation}_{sent,dropped,delayed}_total`
(plus `relay_intervention_record_*` in `"per_robot"` mode).
The historical byte/message counters count a message when it is sent, whether
or not it is later lost.

## 3. Planner cue effectiveness

### `planner_hab_mode="shared"` (default, historical)

One planner field `planner_hab` (cells x cues). Every completion anywhere
depletes it immediately; it recovers every step. Every robot, B5's candidate
scoring (`TaskGenerator`, `stl_hab`), the B4 STL valuation and the plan
procedure's snapshots (`decision_snapshot_from_sim_locals`, `planner_hab`) read
this field. This is the idealisation that every robot learns every
intervention instantly.

### `planner_hab_mode="per_robot"` (decision 17)

Each robot r holds its own `HabituationField` (`robot_information.py`), built
only from the interventions r has received:

* its own completions, applied at completion time;
* other robots' completions, from habituation records that reached r
  (subject to delay and drop).

It uses the planner routine (`planner_habituation_T_rec_s/kappa/gamma`, the
`planner_habituation_update_model` update) with the same `recover(dt)` call
per step as the shared field. A record that arrives after its event time is
inserted at its own time and the field is replayed from a checkpoint
(`RobotHabituationState.apply`), so r's field always equals the field it would
hold had it received the same set of interventions on time. With no delay and
no drop every robot's field equals the shared field bit for bit
(tests/test_communication_information.py).

Uses of r's own field in the simulator:

* the planner effectiveness stamped on r's own intervention feedback
  (`planner_eta_at_apply`, amplitude q_hat * beta) when forecast correction or
  the consistent estimator is on;
* the metric `eta_planner_at_application_*`.

Accessor for the plan procedure: `_planner_hab_for_robot(rid)` in the
simulator locals (also `planner_hab_by_robot.field(rid)`); it returns the live
field, so callers copy before mutating. In `"shared"` mode it returns
`planner_hab`.

The shared field `planner_hab` is still maintained in `"per_robot"` mode as
the union of all interventions (diagnostics, `habituation_eta_*` metrics). The
live B5 candidate scoring and the B4 STL valuation read the deciding robot's own
field (`TaskGenerator.generate(..., stl_hab_for_robot_fn=_planner_hab_for_robot)`,
commit 4bc5562); in `"shared"` mode the function is None and the fleet field is
read exactly as before. B4 keeps central visibility of tasks and estimators in
`"per_robot"` mode (assumption A3); only cue effectiveness is per robot (user
decision 2026-10-22).

### Plan procedure with per-robot information sets

In `"per_robot"` mode the plan procedure (`planner_procedure="plan"`: C_plan,
D_plan, E_plan, E_plan_floor) uses per-robot information sets automatically
(`scenario_rollout.robot_information_snapshot`, installed by the simulator; no
extra parameter). Each robot r's candidates are generated and evaluated on r's
own snapshot, pi_0 is evaluated per robot, each candidate's feasibility and gate
use its own robot's pi_0, the fleet admits the best admissible U across robots,
and a committed deviation enters every robot's snapshot (task state is
centralized). r simulates the whole fleet with ITS OWN beliefs (user answer
2026-10-22):

* planner world: r's own estimator alone on every node;
* every robot's estimator in r's rollouts (the model its B5 continuation and
  candidate scoring read): a copy of r's estimator;
* cue effectiveness read by every robot's B5 and by the world's q_hat * beta:
  r's own field (`_planner_hab_for_robot(r)`);
* B5-facing record of completed actions (pruning, repeat block): the record r
  knows (`_known_deterrences_for_robot(r)`): r's own completions at once, the
  other robots' completions when their intervention record reaches r (table row
  6; same message id, delay and drop as the habituation record), in event-time
  order with the 200-entry cap of `recent_deterrences`;
* the other robots' poses, goals and tasks: the centralized task state;
* the other robots' detection histories (`Robot.recent_events`, read by B5's
  detection-cluster seeds): r believes only the detections RELAYED to r (user
  decision 2026-10-22, former question Q3), with the relay's delay and drop.
  TODO(SIM): at 704722c the snapshot still keeps the fleet state
  (`scenario_rollout.robot_information_snapshot`); the simulator workstream
  implements the decided rule.

The oracle keeps the truth world and uses r's policy side. Prop. 2 is reported
per robot: every robot's own J-hat of the executed policy against the realized
J (`J_hat_executed_by_robot`, summary `plan_pr_*`). Unsupported (clear errors):
per-robot information with timed recovery, and with the consistent estimator.

### Initial state (decision 22)

`initial_hab_state_path` sets the TRUTH field from the truth field in a file
written by `save_final_hab_state_path` at the end of an earlier run (truth from
truth). The PLANNER starts fresh (eta = 1 for every cell and cue, every robot)
for every system: the robots did not record the prior use (user decision
2026-10-22; no informed-planner reference). Thesis wording for the fresh vs
depleted difference: "startup after unrecorded prior use". TODO(SIM): at
704722c the file also loads the shared planner field (and every per-robot field
starts from it); the simulator workstream adds the planner-fresh switch.

## 4. Other information the robots share (unchanged)

* Task state (active, completed, consumed task keys) and dispatch are
  centralized: every robot's dispatch sees every task immediately.
* In `"shared"` mode the plan procedure's planner world
  (`planner_forecast_from_sim_locals`) is the union of every robot's estimator;
  it does not model message delay or loss, nor messages still in transit. In
  `"per_robot"` mode it is the candidate's robot's estimator (section 3).
* The disturbance injections (`travel_speed_error`, `arrival_burst`) and the
  truth demand step (`mu_step_time_s/mu_step_factor`) are not communicated to
  any robot; planner ETAs and the planner's rollouts use the nominal speed and
  background. The oracle evaluates the truth, so its world includes the burst
  and the step and its truth motion is slower by `travel_speed_error`.

## Answered questions (user decisions 2026-10-22)

* Q1 (relay rules). The estimator relay stays the original lossy rule (border
  radius, debounce, minimum weight); the effectiveness records relay completely
  to every robot. The two rules stay different.
* Q2 (late records). Chronological reconstruction is confirmed: a late record is
  inserted at its event time and the field is replayed (legacy late stamps decay
  by exp(-(t_now - t)/omega)).
* Q3 (other robots' detections). r believes only the detections relayed to r
  (section 3; implementation pending in the simulator workstream).

## Unsupported combinations (clear errors)

* Per-robot information sets with timed recovery (`PlanProcedure` raises
  ValueError).
* Per-robot information sets with the consistent estimator (the simulator raises
  ValueError at start).

No communication question is open.
