# Time-Aware Deployment Score

This formulation keeps predictive task generation unchanged and changes only how predictive tasks are ranked at deployment time.

## Motivation

The previous lead-time formulations still relied heavily on generation-time task value. That means a predictive task could keep roughly the same attractiveness even though:

- the forecast event was getting closer,
- the robot ETA changed,
- reactive pressure increased, or
- the task became infeasible before deployment.

The new formulation recomputes predictive score at deployment time.

## Equation

For a predictive task \(i\) at deployment time \(t\):

\[
s_i(t) = t^{event}_i - t - \eta_i(t) - \tau_i
\]

where:

- \(t^{event}_i\) is the forecast event time,
- \(\eta_i(t)\) is the current ETA for the assigned robot,
- \(\tau_i\) is the action service time.

The time-aware score is:

\[
S_i(t) =
V_i \, C_i \, G(s_i(t))
 + w_d \, U(s_i(t))
 - w_\eta \, \eta_i(t)
 - w_q \, q_{react}(t)
\]

with:

\[
V_i = \max(\text{utility}_i,\ \Delta J_i,\ 0)
\]

\[
C_i =
\begin{cases}
p^{event}_i \cdot selection\_weight_i & \text{for model-scored deterring tasks}\\
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

where:

- \(T_d\) is `predictive_time_score_deadline_scale_s`,
- \(w_d\) is `predictive_deadline_weight`,
- \(w_\eta\) is `predictive_eta_penalty_weight`,
- \(w_q\) is `predictive_time_score_reactive_pressure_weight`,
- \(\lambda_{miss}\) is `predictive_time_score_infeasible_penalty`,
- \(q_{react}(t) = \frac{N_{react}(t)}{N_{react}(t)+1}\).

## Default test values

- `predictive_selection_policy = "time-aware"`
- `predictive_time_score_deadline_scale_s = 120.0`
- `predictive_time_score_reactive_pressure_weight = 5.0`
- `predictive_time_score_infeasible_penalty = 25.0`
- `predictive_confidence_source = "p_event_times_selection_weight"`

## Interpretation

Compared with the older lead-time formulations:

- tasks closer to their event time gain urgency smoothly,
- infeasible tasks are penalized strongly instead of lingering with stale value,
- reactive pressure reduces predictive attractiveness in real time,
- the score is recomputed at deployment rather than treated as mostly fixed after generation.
