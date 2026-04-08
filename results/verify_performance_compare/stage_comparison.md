# Simplification Stage Comparison

This file summarizes how each staged planner/control layer changes the thesis baselines.

Main/current reference stage: `s5_current_thesis_profile`

## Key Metrics

```text
                stage_key     module_name  proposed_vs_prediction_exposure_improve_pct  proposed_vs_reactive_exposure_improve_pct  proposed_vs_prediction_response_improve_pct  proposed_vs_reactive_response_improve_pct  proposed_vs_prediction_comm_change_pct  proposed_vs_reactive_comm_change_pct  proposed_model_accepted_mean  proposed_model_completed_mean  proposed_total_planner_rejections_mean  delta_main_proposed_exposure_mean  delta_main_proposed_model_completed_mean  delta_main_proposed_total_planner_rejections_mean
        s1_risk_open_core DeterrentSystem                                          0.0                                        0.0                                          NaN                                        NaN                                     NaN                                -100.0                           3.0                            1.0                                    41.0                                0.0                                       1.0                                               41.0
s5_current_thesis_profile DeterrentSystem                                          0.0                                        0.0                                          NaN                                        NaN                                     NaN                                -100.0                           0.0                            0.0                                     0.0                                0.0                                       0.0                                                0.0
```

## Stage Notes

### s1_risk_open_core: Main Core With Risk Gate Open
- Module: `DeterrentSystem`
- Description: Same stripped-down main runtime as stage 1, but with the heuristic preventive risk threshold fixed at 0.0 so the model-scored preventive branch is active and can be debugged before later protection layers are added back.
- Adds back: Keep the main runtime core. | Force the heuristic preventive risk gate open (threshold 0.0, scale 1e-4).
- Proposed vs prediction-only: exposure=0.000%, response=nan%, comm=nan%
- Proposed vs reactive: exposure=0.000%, response=nan%, comm=-100.000%
- Preventive yield: accepted=3.000, completed=1.000, birds_deterred_pct=0.000, planner_rejections=41.000
- Bird-deterrence comparison: vs prediction=0.000 pts, vs reactive=0.000 pts
- Versus main/current stage `s5_current_thesis_profile`: exposure_delta=0.000, response_delta=nan, comm_delta=0.000, completed_delta=1.000, planner_rejections_delta=41.000

### s5_current_thesis_profile: Current Thesis Profile
- Module: `DeterrentSystem`
- Description: Current thesis-facing proposed runtime: frozen calibration plus the named planner profile used for thesis confirmation work.
- Adds back: Frozen calibration reuse. | Current thesis planner profile.
- Proposed vs prediction-only: exposure=0.000%, response=nan%, comm=nan%
- Proposed vs reactive: exposure=0.000%, response=nan%, comm=-100.000%
- Preventive yield: accepted=0.000, completed=0.000, birds_deterred_pct=0.000, planner_rejections=0.000
- Bird-deterrence comparison: vs prediction=0.000 pts, vs reactive=0.000 pts
- Versus main/current stage `s5_current_thesis_profile`: exposure_delta=0.000, response_delta=nan, comm_delta=0.000, completed_delta=0.000, planner_rejections_delta=0.000
