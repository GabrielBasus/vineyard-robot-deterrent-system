# Reservation Policy Meeting Notes

## Current Status

The latest high-load pilot tests `unc`, hard reserved-capacity policies, random reserved-capacity ablations, and the more selective `res_idle_feasible_confidence` policy with model-scored preventive deterring disabled. This keeps the experiment closer to the April thesis framing:

```text
predictive field -> patrol target -> detection -> reactive deterring task
```

The pilot now reaches meaningful load regimes:

| Case | Observed reactive load | Estimated reactive load | Interpretation |
|---|---:|---:|---|
| `3 robots` | `0.639` | `1.792` | Moderate/high-load case below observed saturation. |
| `2 robots` | `1.417` | `2.346` | Saturated/overloaded case. |

This means the latest pilot is no longer only a low-load test. It is testing the regime where reservation should start to matter.

## Main Conclusions

### 1. The original hard reservation policy is not supported yet

The hard `res` policy still loses to `unc` on value-weighted exposure in both tested high-load cases.

| Case | Best hard `res` | Exposure vs `unc` | Response vs `unc` | Reactive completion drop | Urgent overrides |
|---|---|---:|---:|---:|---:|
| `2 robots` | `res_0p4` | `0.363%` worse | `7.1%` slower | `0.168` | `33,282` |
| `3 robots` | `res_0` | `0.456%` worse | `2.5%` faster | `0.167` | `47,280` |

Interpretation:

- Hard reservation is too blunt.
- It creates urgent reactive override pressure instead of managing it.
- Even when response time improves, it loses too much reactive completion quality and does not reduce exposure.

Meeting point:

- Do not claim that the hard reserved-capacity policy currently beats mixed-greedy `unc`.
- The April hard-reservation idea should be described as needing modification, not as a completed success.

### 2. Random reservation competing with utility reservation is a warning sign

The best random-reservation variant beats the best hard utility-reservation variant on exposure in both high-load cases.

| Case | Best random `res_rand` | Exposure vs `unc` | Interpretation |
|---|---|---:|---|
| `2 robots` | `res_rand_0p2` | `0.292%` worse | Random reservation is less bad than hard utility reservation. |
| `3 robots` | `res_rand_0p1` | `0.206%` worse | Predictive scoring is not clearly adding value inside hard reservation. |

Interpretation:

- The reservation mechanism dominates the result.
- The current utility-ranked predictive choice is not yet clearly better than random selection.
- This weakens the claim that the predictive scoring component is producing useful task choices under the hard reservation policy.

Meeting point:

- Ask whether the thesis should still emphasize predictive scoring, or instead emphasize load-regime behavior and feasible dispatch constraints.

### 3. The idle-feasible-confidence policy is the most promising direction

`res_idle_feasible_confidence` does not beat `unc` on exposure, but it changes the tradeoff in a useful way at `3 robots`.

| Case | IFC exposure vs `unc` | IFC response vs `unc` | IFC travel vs `unc` | Reactive completion drop |
|---|---:|---:|---:|---:|
| `3 robots` | `0.122%` worse | `18.1%` faster | `1.0%` lower | `0.084` |
| `2 robots` | `0.380%` worse | `20.4%` slower | `7.4%` higher | `0.098` |

Interpretation:

- At observed load below one, IFC nearly matches `unc` exposure while improving response time and slightly reducing travel.
- At observed load above one, IFC is not usable because the fleet is overloaded by reactive demand.
- IFC reduces the damage of hard reservation but does not yet prove the reservation hypothesis.

Meeting point:

- A defensible framing may be: selective reservation is a bounded tradeoff policy below saturation, not a universal improvement over `unc`.

### 4. IFC is independent of `rho` in the current sweep

The IFC results are identical for every swept reservation fraction.

Interpretation:

- The testbench does pass different `reservation_fraction` values into the configs.
- The flat IFC curve is probably not a simple config bug.
- IFC only uses `rho` inside the reservation-claim branch.
- The idle, reactive-pressure, feasibility, and confidence gates appear to dominate the decision before `rho` can matter.

Current dispatch condition for IFC is effectively:

```text
claim predictive work only if:
    predictive_share < rho
    robot is idle
    reactive_pressure <= threshold
    predictive task is deadline-feasible
    predictive confidence >= threshold
```

If these gates block the claim, the policy falls back to reactive work or opportunistic predictive work. Those fallback paths are independent of `rho`.

Meeting point:

- Do not describe the IFC result as a successful `rho` tuning result.
- Describe it as evidence that gating is more important than fixed reservation fraction in the current implementation.

### 5. The current system replans periodically, not when robots become idle

The current system has two separate mechanisms:

| Mechanism | Trigger | Effect |
|---|---|---|
| Full task generation / assignment / admission | Fixed `task_replan_period_s` | Generates new tasks, prunes stale tasks, assigns tasks, admits active tasks. |
| Per-step goal selection | Every simulation step | Lets a robot choose from already-active tasks assigned to it. |

If a robot becomes idle between replans, it can immediately take an already-assigned active task. However, it does not trigger fresh task generation just because it became idle.

Interpretation:

- IFC requires `robot_is_idle`, but the system may not generate a new predictive opportunity at the moment a robot becomes idle.
- This can underuse the exact idle capacity that IFC is trying to exploit.
- The policy may look conservative partly because the planning loop is periodic rather than event-triggered.

Meeting point:

- Ask whether idle-triggered lightweight replanning is consistent with the April thesis idea.
- This may be a better next modification than adding another reservation formulation.

## Possible Thesis Reframing

The strongest current framing is not:

```text
reservation beats unc
```

The stronger framing is:

```text
the April load model defines when predictive reservation is usable
```

Using the April load model:

```text
rho_load = lambda_react * E[tau_service,R] / N
```

A practical policy envelope could be:

```text
if observed rho_load < 1 and predictive tasks are feasible/confident:
    allow selective predictive reservation
else:
    fall back to unc or reactive-priority dispatch
```

Supported by current pilot:

- At `3 robots`, observed load is `0.639`; IFC is close to usable.
- At `2 robots`, observed load is `1.417`; IFC degrades.

Meeting point:

- Ask whether this operating-envelope claim is acceptable as the thesis direction if hard reservation does not become a clean winner.

## Proposed Next Experiments

### Experiment 1: IFC Gate Diagnostic

Purpose:

- Determine why IFC is independent of `rho`.

Add telemetry counters:

- `ifc_selected_by_reservation_claim`
- `ifc_selected_by_predictive_fallback`
- `ifc_blocked_by_not_idle`
- `ifc_blocked_by_reactive_pressure`
- `ifc_blocked_by_confidence`
- `ifc_blocked_by_slack`
- `ifc_blocked_by_predictive_share_above_rho`

Claim tested:

```text
IFC is flat across rho because feasibility/idle/confidence/reactive-pressure gates dominate before the reservation-share condition becomes active.
```

Decision rule:

- If most blocks are from pressure/idle/confidence/slack, tune those gates instead of `rho`.
- If many blocks are from `predictive_share_above_rho`, then `rho` is active and the flat result may indicate a deeper scoring/lifecycle issue.

### Experiment 1b: Idle-Replan Diagnostic

Purpose:

- Determine whether robots are idle while no suitable active predictive task is assigned.

Add telemetry:

- `idle_with_no_assigned_task_time`
- `idle_with_predictive_candidates_available_time`
- `idle_wait_until_next_replan_s`
- `idle_replan_opportunities_count`
- `idle_robot_predictive_claim_missed_count`

Claim tested:

```text
IFC underuses predictive capacity because idle robots wait for the next periodic replan instead of triggering fresh predictive assignment.
```

Decision rule:

- If idle robots often wait with no assigned task before the next replan, add event-triggered replanning.
- If idle robots already have tasks but reject them through confidence/slack/pressure gates, tune the gates instead.

### Experiment 2: IFC Gate Sweep

Purpose:

- Tune the active IFC gates rather than sweeping `rho`.

Recommended sweep parameters:

| Parameter | Suggested values | Reason |
|---|---|---|
| `reactive_pressure_max_for_predictive` | `0.25`, `0.5`, `0.75`, `1.0` | Controls how much reactive queue pressure blocks predictive work. |
| `predictive_confidence_min` | `0.1`, `0.25`, `0.4` | Controls predictive selectivity. |
| `predictive_slack_min_s` | `0`, `15`, `30` | Controls deadline feasibility strictness. |
| `predictive_lead_time_max_eta_s` | `90`, `120`, `180` | Controls how far robots may travel for predictive tasks. |

Use:

- `3 robots` first, because that is where IFC is closest to useful.
- `2 seeds` for pilot.
- Then confirm best candidate with `5 seeds`.

Claim tested:

```text
Selective reservation can produce a Pareto tradeoff below saturation: near-unc exposure with faster response time and lower travel.
```

Success criteria:

- Exposure no worse than `unc` by more than a small tolerance, or better than `unc`.
- Response time better than `unc`.
- Travel no worse than `unc`.
- Reactive completion loss smaller than current IFC.
- Urgent overrides materially lower than hard reservation.

### Experiment 3: Load-Envelope Confirmation

Purpose:

- Test whether the usable region is tied to observed load factor.

Run the best IFC gate setting at:

| Robots | Expected role |
|---:|---|
| `4` | Below saturation / nominal load |
| `3` | Moderate/high load |
| `2` | Overload |

Compare against:

- `unc`
- best hard `res`
- `res_rand`

Claim tested:

```text
Selective reservation is usable for observed rho_load < 1 and harmful for observed rho_load > 1.
```

Expected result if the operating-envelope framing is correct:

- `4r` and `3r`: IFC should be competitive with `unc`, possibly trading tiny exposure cost for faster response/lower travel.
- `2r`: IFC should fall back toward `unc` behavior or be disabled; if not, it should degrade.

### Experiment 4: Conditional Policy Test

Purpose:

- Test the practical control rule implied by the load model.

Policy:

```text
if observed rho_load < 1:
    use tuned IFC
else:
    use unc
```

Claim tested:

```text
A load-aware switch can retain IFC benefits below saturation while avoiding IFC failures above saturation.
```

Success criteria:

- Matches or improves `unc` exposure across load cases.
- Improves response time or travel in below-saturation cases.
- Does not lose reactive completion under overload.

## Suggested System Changes

These are the most useful changes to consider before adding new policy families.

### Change 1: Add IFC branch diagnostics

Problem:

- IFC is flat across `rho`, but the current metrics do not say which gate is binding.

Suggested change:

- Count the reason each IFC predictive claim succeeds or fails.

Expected benefit:

- Determines whether to tune `rho`, pressure, confidence, slack, or idle logic.

Risk:

- Low. This is telemetry-only and should not change behavior.

Priority:

- Highest.

### Change 2: Add idle-triggered lightweight replanning

Problem:

- Full task generation is periodic. A robot that becomes idle between replans may not receive a fresh predictive task until the next scheduled cycle.

Suggested change:

```text
if robot becomes idle
and no active assigned task exists
and time_since_last_replan >= min_idle_replan_gap:
    run lightweight task generation / assignment
```

Recommended safeguards:

- Use a minimum gap such as `15-30 s` to avoid excessive replanning.
- Only trigger if at least one robot is idle with no active assigned task.
- Preserve urgent reactive handling.
- Track how often the trigger fires.

Expected benefit:

- Better matches IFC's intent: use idle capacity opportunistically for predictive work.
- May increase predictive usefulness without forcing hard reservation.

Risk:

- Could increase computation and task churn if not rate-limited.
- Could make comparisons less aligned with the original April fixed-period setup, so it should be tested as a separate modification.

Priority:

- High after diagnostics.

### Change 3: Make reservation load-aware

Problem:

- Hard reservation is harmful when observed reactive load exceeds one.

Suggested change:

```text
if observed_rho_load >= 1:
    disable predictive reservation or fall back to unc
else:
    allow selective IFC-style predictive claims
```

Expected benefit:

- Prevents reservation from consuming capacity when reactive demand alone saturates the fleet.
- Uses the April load model as an operating-envelope rule.

Risk:

- Requires reliable online load estimation.
- Needs a smoothing window to avoid policy oscillation.

Priority:

- High if the thesis pivots to a load-envelope claim.

### Change 4: Tune active IFC gates instead of `rho`

Problem:

- `rho` is not binding for IFC.

Suggested sweep:

| Parameter | Values |
|---|---|
| `reactive_pressure_max_for_predictive` | `0.25`, `0.5`, `0.75`, `1.0` |
| `predictive_confidence_min` | `0.1`, `0.25`, `0.4` |
| `predictive_slack_min_s` | `0`, `15`, `30` |
| `predictive_lead_time_max_eta_s` | `90`, `120`, `180` |

Expected benefit:

- Finds whether IFC can become a defensible tradeoff policy below saturation.

Risk:

- Search space can grow quickly. Keep this bounded and start with `3 robots`.

Priority:

- Medium-high after branch diagnostics.

### Change 5: Convert hard reservation into opportunistic reservation

Problem:

- The April hard policy reserves predictive work even when it can create reactive pressure.

Suggested change:

Replace:

```text
if predictive_share < rho:
    choose predictive
```

with:

```text
if predictive_share < rho
and observed_rho_load < 1
and robot is idle or switching cost is low
and predictive task is feasible/confident:
    choose predictive
```

Expected benefit:

- Keeps the spirit of reservation while avoiding the overcommitment failure.

Risk:

- This is no longer the original April hard-reservation policy. It should be framed as the modified policy.

Priority:

- Medium.

### Change 6: Add hysteresis to load-aware switching

Problem:

- A simple threshold at `rho_load = 1` can oscillate if the estimate is noisy.

Suggested change:

```text
enable IFC if observed_rho_load < 0.85
disable IFC if observed_rho_load > 1.00
otherwise keep previous mode
```

Expected benefit:

- Stable operating-envelope controller.

Risk:

- Adds another small parameter pair.

Priority:

- Medium, only if load-aware switching is pursued.

## Claims That Are Currently Supported

The data supports these cautious claims:

- Hard fixed-fraction reservation is too aggressive in the current system.
- Mixed-greedy `unc` is a strong baseline.
- The April load model is useful for interpreting when predictive reservation may be usable.
- Selective gating is more promising than hard reservation.
- IFC may be useful below observed saturation as a response-time/travel tradeoff policy.

## Claims That Are Not Yet Supported

The data does not yet support these claims:

- Reservation globally beats `unc`.
- Hard `res(rho)` is the right final policy.
- Utility-ranked predictive reservation beats random predictive reservation.
- IFC has been tuned through `rho`.
- IFC is deployment-ready.

## Recommended Advisor Question

The main question to ask:

```text
Given that hard reservation is not winning, but selective IFC nearly matches unc below saturation while improving response time, should the thesis pivot from "reservation beats greedy" to "load-aware feasibility-gated predictive reservation defines a usable operating envelope"?
```

Secondary questions:

- Is a tradeoff claim acceptable if exposure is near-baseline but response time and travel improve?
- Should the main contribution be the load-aware operating envelope rather than the hard reservation policy?
- Should we run one bounded gate-tuning pass before deciding to pivot?
- What tolerance around `unc` exposure is acceptable for claiming a useful operational tradeoff?
- Is idle-triggered replanning a valid modification, or does the thesis need to keep fixed-period replanning for fairness?
- Should the next experiment prioritize diagnostics/telemetry or immediately test the load-aware IFC switch?
