# Feedback Patrol Stability Diagnostic

## Parameters

- `runs`: `2`
- `seed_start`: `2026`
- `T_end`: `2400.0`
- `dt`: `5.0`
- `warmup_s`: `1800.0`
- `task_replan_period_s`: `60.0`
- `patrol_hotspot_filter_mode`: `percentile`
- `patrol_hotspot_score_percentile`: `97.0`
- `alpha_inhib`: `0.45`
- `omega_inhib`: `600.0`
- `mu_base`: `5e-05`
- `bg_ema`: `1e-06`

## Mode Summary

### prediction_only

- `carryover_fraction_mean`: `0.0`
- `turnover_fraction_mean`: `0.975`
- `same_robot_replacements_per_replan_mean`: `2.0125`
- `nonpatrol_preemptions_per_replan_mean`: `0.037500000000000006`
- `mean_patrol_lifetime_s`: `607.5182364299507`
- `mean_replan_presence_count`: `0.4962293388429752`
- `completed_fraction_mean`: `0.48512396694214877`
- `replaced_fraction_mean`: `0.334280303030303`
- `preempted_fraction_mean`: `0.006215564738292011`
- `dropped_fraction_mean`: `0.15568181818181817`
- `final_exposure_mean`: `3927.474371721066`
- `final_response_s_mean`: `114.0692067529933`
### proposed_feedback_only

- `carryover_fraction_mean`: `0.0`
- `turnover_fraction_mean`: `0.9375`
- `same_robot_replacements_per_replan_mean`: `1.7625`
- `nonpatrol_preemptions_per_replan_mean`: `0.037500000000000006`
- `mean_patrol_lifetime_s`: `635.6962025316456`
- `mean_replan_presence_count`: `0.45835905349794237`
- `completed_fraction_mean`: `0.5230452674897119`
- `replaced_fraction_mean`: `0.2925668724279835`
- `preempted_fraction_mean`: `0.006198559670781893`
- `dropped_fraction_mean`: `0.1595164609053498`
- `final_exposure_mean`: `3851.2210425368075`
- `final_response_s_mean`: `111.18052564790864`

## Paired Delta Summary

- `delta_carryover_fraction_mean_prop_minus_pred`: `0.0`
- `delta_turnover_fraction_mean_prop_minus_pred`: `-0.03749999999999998`
- `delta_mean_patrol_lifetime_s_prop_minus_pred`: `28.177966101694892`
- `delta_same_robot_replacements_per_replan_prop_minus_pred`: `-0.25`
- `delta_nonpatrol_preemptions_per_replan_prop_minus_pred`: `0.0`
- `delta_completed_fraction_prop_minus_pred`: `0.03792130054756315`
- `delta_dropped_fraction_prop_minus_pred`: `0.0038346427235316227`
- `delta_final_exposure_prop_minus_pred`: `-76.25332918425852`
- `delta_final_response_s_prop_minus_pred`: `-2.8886811050846646`

## Conclusions

- Feedback does not reduce patrol carry-over on average.
- Feedback does not increase same-robot patrol replacements per replan.
- Feedback does not shorten patrol-task lifetime on average.
