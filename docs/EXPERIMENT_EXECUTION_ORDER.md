## Experiment Execution Order

1. **Model calibration** (`experiments/run_sestpp_calibration_sweep.py`): freeze the intervention-aware SESTPP settings using paired log-loss, Brier, and NLL improvements with CI95 support.
2. **Field divergence lab** (`experiments/compare_field_divergence_lab.py`): verify the calibrated proposed field diverges from prediction-only and that the divergence survives hotspot filtering and patrol generation.
3. **Field divergence confirm** (`experiments/run_field_divergence_confirm_lab.py`): rerun matched proposed-vs-prediction pairs across seeds and require CI95-backed acceptance on the divergence and patrol-overlap metrics.
4. **Planner / assignment tuning** (`experiments/run_assignment_tuning_sweep_lab.py`): tune dispatch and gating only after field divergence is confirmed; reject solver failures and weak-gain/high-communication settings.
5. **Assignment-method comparison** (`experiments/run_assignment_method_comparison_lab.py`, `plots/plot_assignment_method_comparison_lab.py`, optional): run only if solver choice still matters after the main tuning sweep.
6. **Robot scaling / long-horizon confirmation** (`experiments/run_robot_scaling_experiment.py`): confirm exposure gains grow with robot count, response does not collapse, communication stays controlled, and model-scored deterring gain rises.
7. **Habituation-aware STL addendum** (`experiments/run_habituation_stl_production_ladder.py`): run the B0-B4 ladder and B1/B3/B4 confirmatory batch when the thesis claim includes habituation-aware predictive value. Use paired habituation-on/off controls and summarize with `experiments/summarize_habituation_stl_ladder.py`.

## Habituation-Aware STL Addendum

Use this addendum after the core production pipeline is stable. The purpose is not to retune the dispatcher; it isolates the predictive value function under habituating ground truth.

Baseline ladder:

- B0: reactive-only reference
- B1: legacy unconstrained predictive baseline
- B2: reserved dispatcher with legacy deltaJ value
- B3: reserved dispatcher with STL exposure/coverage value
- B4: reserved dispatcher with STL exposure/coverage/habituation value

Acceptance pattern:

- B4 should beat B3 under habituating truth.
- B4 should collapse to B3 when habituation is disabled.
- Mechanism metrics should show higher `eta_at_apply`, higher cue variety, and higher truth suppression for B4 under habituating truth.

Current confirmed result: `docs/HABITUATION_STL_CONFIRMATORY_RESULTS.md`.