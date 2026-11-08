# Arrival-Offset Predictive Timing

This timing mode addresses the earlier issue where predictive task event times were tied too directly to a coarse forecast horizon. The new goal is:

- advance the task far enough into the future for a robot to arrive before the event,
- but not so far that the task loses forecast value by aiming too deep into the future.

## Definitions

For a predictive task generated at time \(t_0\):

\[
L_{\mathrm{req}} = T_{\mathrm{replan}} + \eta + \tau_{\mathrm{service}} + b
\]

where:

- \(T_{\mathrm{replan}}\) is the task replan interval,
- \(\eta\) is the current ETA to the task,
- \(\tau_{\mathrm{service}}\) is the service time,
- \(b\) is the configured safety buffer.

This is the minimum lead required for the robot to arrive and act before the event.

We also define a coarse forecast cap:

\[
L_{\mathrm{cap}} = \max\left(L_{\mathrm{req}},\ \min\left(H_{\mathrm{forecast}},\ T_{\mathrm{replan}} + \eta_{\max} + \tau_{\mathrm{service}} + b\right)\right)
\]

where:

- \(H_{\mathrm{forecast}}\) is the forecast horizon,
- \(\eta_{\max}\) is the configured worst-case ETA cap.

This prevents the event from being pushed arbitrarily far into the future.

## Useful Margin Budget

Instead of using the full cap gap, the system only allows a smaller useful forward margin:

\[
M_{\mathrm{useful}} = \min\left(L_{\mathrm{cap}} - L_{\mathrm{req}},\ b + \frac{1}{2}\tau_{\mathrm{service}}\right)
\]

This keeps the event just ahead of the robot’s required arrival time rather than deep into the horizon.

## Confidence-Scaled Offset

Let \(c \in [0,1]\) be the predictive confidence term already derived from the task:

\[
c = \max(p_{\mathrm{event}},\ risk_{\mathrm{conf}},\ selection\_weight)^{\rho}
\]

where \(\rho\) is `predictive_lead_time_risk_power`.

The final predictive event offset is:

\[
L_{\mathrm{event}} = L_{\mathrm{req}} + c \cdot M_{\mathrm{useful}}
\]

and the generated event time is:

\[
t_{\mathrm{event}} = t_0 + L_{\mathrm{event}}
\]

## Exported Debug Fields

The timing mode writes:

- `predictive_required_lead_time_s = L_req`
- `predictive_event_offset_s = L_event`
- `predictive_offset_margin_s = c * M_useful`
- `predictive_offset_cap_s = L_cap - L_req`

## Interpretation

- Low confidence keeps the event close to the minimum required arrival lead.
- Higher confidence allows a modest extra forward offset.
- The offset is bounded by both the forecast horizon and a small useful margin budget, so tasks do not drift unnecessarily far into the future.
