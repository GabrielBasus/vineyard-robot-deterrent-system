# Deferred-Action Predictive Dispatch

## Objective
Generate predictive opportunities early, but delay final action choice until dispatch so the planner can output concrete `robot -> task` assignments using the current robot state.

## Predictive opportunity representation
Each predictive opportunity now keeps a mode-agnostic opportunity key and a per-mode variant set:

\[
o = (x, y, t_{\mathrm{event}}, t_{\mathrm{release}}, p_{\mathrm{event}}, w_{\mathrm{sel}}, r_{\mathrm{conf}}, \mathcal{M})
\]

where each mode variant \(m \in \mathcal{M}\) stores:

\[
v_m = \left(\Delta J_m,\; \frac{\Delta J_m}{c_m},\; c_m,\; \tau_m\right)
\]

## Hybrid ETA basis
For a candidate robot \(r\) and predictive opportunity \(o\):

Idle robot:

\[
\eta_{\mathrm{hybrid}}(r,o) = \eta_{\mathrm{live}}(r,o)
\]

Robot already committed to the same goal:

\[
\eta_{\mathrm{hybrid}}(r,o) = \eta_{\mathrm{live}}(r,o)
\]

Robot committed to a different goal:

\[
\eta_{\mathrm{hybrid}}(r,o) =
\eta_{\mathrm{goal}}(r,g_r)
+ c_{\mathrm{switch}}
+ \eta(g_r \rightarrow o)
\]

where:
- \(g_r\) is the robot's current committed goal,
- \(c_{\mathrm{switch}}\) is the reassignment / switching penalty,
- \(\eta(g_r \rightarrow o)\) is the travel time from the current goal to the predictive target.

## Dispatch-time mode resolution
For each feasible robot-mode pair \((r,m)\), compute deadline slack:

\[
s_{r,m}(t) = t_{\mathrm{event}} - t - \eta_{\mathrm{hybrid}}(r,o) - \tau_m
\]

Confidence term:

\[
C_o = p_{\mathrm{event}} \cdot w_{\mathrm{sel}}
\]

The current implementation reuses the existing time-aware predictive score at dispatch time over the resolved variants:

\[
S_{r,m}(t)
= V_m \, C_o \, G(s_{r,m}(t))
- w_{\eta}\,\eta_{\mathrm{hybrid}}(r,o)
- w_q\,q_{\mathrm{react}}(t)
+ w_d\,U_{\mathrm{deadline}}(s_{r,m}(t))
\]

where \(V_m\) follows the configured predictive selection policy (`time-aware`, `time-aware-v2`, etc.).

The dispatch resolver chooses:

\[
m^*(r,o,t) = \arg\max_{m \in \mathcal{M}} S_{r,m}(t)
\]

Then assignment ranking chooses:

\[
r^*(o,t) = \arg\max_r A(r, m^*(r,o,t), o, t)
\]

where \(A\) is the existing robot assignment score with the hybrid ETA substituted for the live-pose ETA term.

## Execution boundary
Only the selected pair \((r^*, m^*)\) is converted into an executable task row. Active tasks therefore remain concrete and contain:
- one `mode`
- one `action`
- one `assigned_primary`

The deferred-mode representation stays internal to planning and dispatch.
