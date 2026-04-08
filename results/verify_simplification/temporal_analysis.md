# Temporal Analysis

This report summarizes how stage performance changes with horizon length and across consecutive time bouts.

Main/current reference stage: `s5_current_thesis_profile`
Native bout window used in this report: `30.0` s

## Stage Summary

```text
                stage_key  final_proposed_vs_prediction_exposure_improve_pct  final_proposed_vs_reactive_exposure_improve_pct  best_horizon_vs_prediction_h  best_horizon_vs_prediction_exposure_improve_pct  best_horizon_vs_reactive_h  best_horizon_vs_reactive_exposure_improve_pct  best_bout_vs_prediction_exposure_improve_pct  best_bout_vs_reactive_exposure_improve_pct  positive_bout_share_vs_prediction  positive_bout_share_vs_reactive  final_proposed_birds_deterred_pct_mean  final_proposed_model_deterring_accepted_mean  final_proposed_model_deterring_generated_mean
        s1_risk_open_core                                                0.0                                              0.0                      0.016667                                              0.0                    0.016667                                            0.0                                           0.0                                         0.0                                0.0                              0.0                                     0.0                                           3.0                                            8.0
s5_current_thesis_profile                                                0.0                                              0.0                      0.016667                                              0.0                    0.016667                                            0.0                                           0.0                                         0.0                                0.0                              0.0                                     0.0                                           0.0                                            0.0
```

## Stage Notes

### s1_risk_open_core: Main Core With Risk Gate Open
- Final horizon (0.02 h): vs prediction=0.000%, vs reactive=0.000%.
- Best cumulative horizon: vs prediction=0.000% at 0.02 h; vs reactive=0.000% at 0.02 h.
- Best time bout: vs prediction=0.000% from 0.01 to 0.02 h; vs reactive=0.000% from 0.01 to 0.02 h.
- Positive-bout share: vs prediction=0.000%, vs reactive=0.000%.
- Horizon trend: vs prediction trend unclear; vs reactive trend unclear.
- Preventive activity by final horizon: generated=8.000, accepted=3.000, completed_tasks=1.000.
- Bird-deterrence by final horizon: proposed=0.000%, prediction_only=0.000%, reactive=0.000%, delta_vs_prediction=0.000 pts, delta_vs_reactive=0.000 pts.

### s5_current_thesis_profile: Current Thesis Profile
- Final horizon (0.02 h): vs prediction=0.000%, vs reactive=0.000%.
- Best cumulative horizon: vs prediction=0.000% at 0.02 h; vs reactive=0.000% at 0.02 h.
- Best time bout: vs prediction=0.000% from 0.01 to 0.02 h; vs reactive=0.000% from 0.01 to 0.02 h.
- Positive-bout share: vs prediction=0.000%, vs reactive=0.000%.
- Horizon trend: vs prediction trend unclear; vs reactive trend unclear.
- Preventive activity by final horizon: generated=0.000, accepted=0.000, completed_tasks=0.000.
- Bird-deterrence by final horizon: proposed=0.000%, prediction_only=0.000%, reactive=0.000%, delta_vs_prediction=0.000 pts, delta_vs_reactive=0.000 pts.
