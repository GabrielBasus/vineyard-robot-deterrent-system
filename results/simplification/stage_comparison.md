# Simplification Stage Comparison

This file summarizes how each staged planner/control layer changes the thesis baselines.

Main/current reference stage: `s5_current_thesis_profile`

## Key Metrics

```text
                stage_key                  module_name  proposed_vs_prediction_exposure_improve_pct  proposed_vs_reactive_exposure_improve_pct  proposed_vs_prediction_response_improve_pct  proposed_vs_reactive_response_improve_pct  proposed_vs_prediction_comm_change_pct  proposed_vs_reactive_comm_change_pct  proposed_model_accepted_mean  proposed_model_completed_mean  proposed_total_planner_rejections_mean  delta_main_proposed_exposure_mean  delta_main_proposed_model_completed_mean  delta_main_proposed_total_planner_rejections_mean
     s0_simple_tasks_core DeterrentSystem_simple_tasks                                     0.000000                                  -0.944497                                     0.000000                                   1.727320                              110.835799                            118.596626                           0.0                            0.0                                 10564.8                         -24.434301                                       0.0                                            10149.4
             s1_main_core              DeterrentSystem                                     0.000000                                  -0.998593                                     0.000000                                  18.904218                               93.045113                            -25.579710                           0.0                            0.0                                 91628.8                          -6.661347                                       0.0                                            91213.4
        s1_risk_open_core              DeterrentSystem                                     2.860082                                   1.890049                                    -0.276884                                  18.679677                               62.781955                            -37.246377                          24.0                           18.6                                 65567.8                         -55.269877                                      18.6                                            65152.4
       s2_direct_conflict              DeterrentSystem                                     0.000000                                  -0.998593                                     0.000000                                  18.904218                               93.045113                            -25.579710                           0.0                            0.0                                 91628.8                          -6.661347                                       0.0                                            91213.4
           s3_persistence              DeterrentSystem                                     0.000000                                  -0.998593                                     0.000000                                  18.904218                               93.045113                            -25.579710                           0.0                            0.0                                 91628.8                          -6.661347                                       0.0                                            91213.4
       s4_capacity_budget              DeterrentSystem                                     0.000000                                  -0.998593                                     0.000000                                  18.904218                               93.045113                            -25.579710                           0.0                            0.0                                 91628.8                          -6.661347                                       0.0                                            91213.4
s5_current_thesis_profile              DeterrentSystem                                     0.000000                                  -1.410997                                     0.000000                                  28.332573                               99.812030                            -26.991758                           0.0                            0.0                                   415.4                           0.000000                                       0.0                                                0.0
```

## Stage Notes

### s0_simple_tasks_core: Simple Tasks Core
- Module: `DeterrentSystem_simple_tasks`
- Description: Smallest end-to-end thesis-consistent branch already present in the repo: zone partitioning, SESTPP feedback, hotspot tasks, preventive tasks, and simple one-task-per-robot management.
- Proposed vs prediction-only: exposure=0.000%, response=0.000%, comm=110.836%
- Proposed vs reactive: exposure=-0.944%, response=1.727%, comm=118.597%
- Preventive yield: accepted=0.000, completed=0.000, birds_deterred_pct=nan, planner_rejections=10564.800
- Bird-deterrence comparison: vs prediction=nan pts, vs reactive=nan pts
- Versus main/current stage `s5_current_thesis_profile`: exposure_delta=-24.434, response_delta=32.737, comm_delta=5720.000, completed_delta=0.000, planner_rejections_delta=10149.400

### s1_main_core: Main Runtime Core
- Module: `DeterrentSystem`
- Description: Main runtime with the same stripped-down planner idea as stage 0: heuristic preventive admission, no protective dispatch heuristics, no capacity throttles, and minimal queueing.
- Adds back: Switch back to the main production runtime.
- Proposed vs prediction-only: exposure=0.000%, response=0.000%, comm=93.045%
- Proposed vs reactive: exposure=-0.999%, response=18.904%, comm=-25.580%
- Preventive yield: accepted=0.000, completed=0.000, birds_deterred_pct=nan, planner_rejections=91628.800
- Bird-deterrence comparison: vs prediction=nan pts, vs reactive=nan pts
- Versus main/current stage `s5_current_thesis_profile`: exposure_delta=-6.661, response_delta=4.038, comm_delta=-115.200, completed_delta=0.000, planner_rejections_delta=91213.400

### s1_risk_open_core: Main Core With Risk Gate Open
- Module: `DeterrentSystem`
- Description: Same stripped-down main runtime as stage 1, but with the heuristic preventive risk threshold fixed at 0.0 so the model-scored preventive branch is active and can be debugged before later protection layers are added back.
- Adds back: Keep the main runtime core. | Force the heuristic preventive risk gate open (threshold 0.0, scale 1e-4).
- Proposed vs prediction-only: exposure=2.860%, response=-0.277%, comm=62.782%
- Proposed vs reactive: exposure=1.890%, response=18.680%, comm=-37.246%
- Preventive yield: accepted=24.000, completed=18.600, birds_deterred_pct=nan, planner_rejections=65567.800
- Bird-deterrence comparison: vs prediction=nan pts, vs reactive=nan pts
- Versus main/current stage `s5_current_thesis_profile`: exposure_delta=-55.270, response_delta=4.165, comm_delta=-630.400, completed_delta=18.600, planner_rejections_delta=65152.400

### s2_direct_conflict: Add Direct Conflict Guard
- Module: `DeterrentSystem`
- Description: Adds only the rule that model-scored preventive tasks must not conflict with active or recent direct-detection work.
- Adds back: Direct-detection conflict protection.
- Proposed vs prediction-only: exposure=0.000%, response=0.000%, comm=93.045%
- Proposed vs reactive: exposure=-0.999%, response=18.904%, comm=-25.580%
- Preventive yield: accepted=0.000, completed=0.000, birds_deterred_pct=nan, planner_rejections=91628.800
- Bird-deterrence comparison: vs prediction=nan pts, vs reactive=nan pts
- Versus main/current stage `s5_current_thesis_profile`: exposure_delta=-6.661, response_delta=4.038, comm_delta=-115.200, completed_delta=0.000, planner_rejections_delta=91213.400

### s3_persistence: Add Persistence Locks
- Module: `DeterrentSystem`
- Description: Adds preventive persistence so admitted model-scored tasks are not dropped immediately on the next replan.
- Adds back: Protect active preventive tasks across replans. | Allow preventive goal locks to survive patrol reassignment pressure.
- Proposed vs prediction-only: exposure=0.000%, response=0.000%, comm=93.045%
- Proposed vs reactive: exposure=-0.999%, response=18.904%, comm=-25.580%
- Preventive yield: accepted=0.000, completed=0.000, birds_deterred_pct=nan, planner_rejections=91628.800
- Bird-deterrence comparison: vs prediction=nan pts, vs reactive=nan pts
- Versus main/current stage `s5_current_thesis_profile`: exposure_delta=-6.661, response_delta=4.038, comm_delta=-115.200, completed_delta=0.000, planner_rejections_delta=91213.400

### s4_capacity_budget: Add Capacity And Budget
- Module: `DeterrentSystem`
- Description: Adds the throttling layer: per-robot preventive budgets, service-rate capacity gating, cycle admission caps, and strict busy-robot fallback.
- Adds back: Preventive budgets. | Capacity gating. | Busy-robot fallback thresholds.
- Proposed vs prediction-only: exposure=0.000%, response=0.000%, comm=93.045%
- Proposed vs reactive: exposure=-0.999%, response=18.904%, comm=-25.580%
- Preventive yield: accepted=0.000, completed=0.000, birds_deterred_pct=nan, planner_rejections=91628.800
- Bird-deterrence comparison: vs prediction=nan pts, vs reactive=nan pts
- Versus main/current stage `s5_current_thesis_profile`: exposure_delta=-6.661, response_delta=4.038, comm_delta=-115.200, completed_delta=0.000, planner_rejections_delta=91213.400

### s5_current_thesis_profile: Current Thesis Profile
- Module: `DeterrentSystem`
- Description: Current thesis-facing proposed runtime: frozen calibration plus the named planner profile used for thesis confirmation work.
- Adds back: Frozen calibration reuse. | Current thesis planner profile.
- Proposed vs prediction-only: exposure=0.000%, response=0.000%, comm=99.812%
- Proposed vs reactive: exposure=-1.411%, response=28.333%, comm=-26.992%
- Preventive yield: accepted=0.000, completed=0.000, birds_deterred_pct=nan, planner_rejections=415.400
- Bird-deterrence comparison: vs prediction=nan pts, vs reactive=nan pts
- Versus main/current stage `s5_current_thesis_profile`: exposure_delta=0.000, response_delta=0.000, comm_delta=0.000, completed_delta=0.000, planner_rejections_delta=0.000
