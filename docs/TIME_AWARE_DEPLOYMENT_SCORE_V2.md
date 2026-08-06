# Time-Aware Deployment Score V2

This formulation completes step 3 and step 4 of the predictive-pipeline fix plan:

- predictive opportunities are deduplicated by opportunity identity instead of being counted per robot snapshot,
- predictive deployment value is recomputed at dispatch time from current timing, confidence, ETA, and reactive pressure,
- predictive tasks can expire once they are no longer feasible.

## Motivation

The first time-aware formulation improved dispatch behavior, but it still used a generation-time base value:

\[
V_i = \max(\text{utility}_i,\ \Delta J_i,\ 0)
\]

That let stale high-utility tasks remain overly attractive even when their predicted intervention benefit had weakened relative to newer tasks.

V2 changes two things:

1. predictive counters track distinct opportunities rather than repeated robot-scoped candidates,
2. the deployment score uses predicted delta-J directly rather than the larger of generation-time utility and delta-J.

## Opportunity Identity

Each predictive task is assigned a predictive opportunity key:

\[
\kappa_i = f(\text{task type}, \text{origin}, \text{mode}, \text{cluster/candidate identity}, \text{event-time bucket})
\]

All predictive candidates with the same \(\kappa_i\) are treated as one underlying opportunity.

This yields three distinct counters:

- `predictive_distinct_generated_total`
- `predictive_distinct_admitted_total`
- `predictive_distinct_completed_total`

These are diagnostic counters. They do not replace the legacy totals; they explain how much repeated snapshot generation was inflating the old counts.

## Feasibility and Expiry

For predictive task \(i\) at dispatch time \(t\):

\[
s_i(t) = t^{event}_i - t - \eta_i(t) - \tau_i
\]

where:

- \(t^{event}_i\) is the forecast event time,
- \(\eta_i(t)\) is the current ETA,
- \(\tau_i\) is the service time.

If \(s_i(t) < -g\), where \(g\) is `predictive_expiry_grace_s`, the task is expired and removed.

## V2 Deployment Score

The time-aware-v2 score is:

\[
S_i^{v2}(t) =
\Delta J_i \, C_i \, G(s_i(t))
+ w_d \, U(s_i(t))
- w_\eta \, \eta_i(t)
- w_q \, q_{react}(t)
\]

with:

\[
C_i =
\begin{cases}
p^{event}_i \cdot selection\_weight_i & \text{for model-scored predictive tasks}\\
1 & \text{for fallback patrol tasks}
\end{cases}
\]

\[
U(s) =
\begin{cases}
\frac{1}{1+s} & s \ge 0\\
-1-|s| & s < 0
\end{cases}
\]

\[
G(s) =
\begin{cases}
\frac{T_d}{T_d+s} & s \ge 0\\
-\lambda_{miss}\left(1 + \frac{|s|}{T_d}\right) & s < 0
\end{cases}
\]

and:

- \(T_d\) is `predictive_time_score_deadline_scale_s`,
- \(w_d\) is `predictive_deadline_weight`,
- \(w_\eta\) is `predictive_eta_penalty_weight`,
- \(w_q\) is `predictive_time_score_reactive_pressure_weight`,
- \(\lambda_{miss}\) is `predictive_time_score_infeasible_penalty`,
- \(q_{react}(t) = \frac{N_{react}(t)}{N_{react}(t)+1}\).

## Difference From V1

V1 used:

\[
V_i = \max(\text{utility}_i,\ \Delta J_i,\ 0)
\]

V2 uses:

\[
V_i^{v2} = \Delta J_i
\]

So V2 favors tasks with stronger predicted intervention benefit now, rather than letting a large frozen generation-time utility dominate dispatch.

## Expected Effect

Compared with the original lead-time and v1 time-aware formulations, v2 is intended to:

- reduce repeated counting of the same predictive opportunity,
- make predictive throughput metrics more honest,
- reduce stale predictive tasks lingering after infeasibility,
- rank predictive tasks by current intervention value rather than static generation-time utility.
