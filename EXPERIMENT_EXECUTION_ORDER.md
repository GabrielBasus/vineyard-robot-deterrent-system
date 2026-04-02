## Experiment Execution Order

1. **Model calibration** (`run_sestpp_calibration_sweep.py`): freeze the intervention-aware SESTPP settings using paired log-loss, Brier, and NLL improvements with CI95 support.
2. **Field divergence lab** (`compare_field_divergence_lab.py`): verify the calibrated proposed field diverges from prediction-only and that the divergence survives hotspot filtering and patrol generation.
3. **Field divergence confirm** (`run_field_divergence_confirm_lab.py`): rerun matched proposed-vs-prediction pairs across seeds and require CI95-backed acceptance on the divergence and patrol-overlap metrics.
4. **Planner / assignment tuning** (`run_assignment_tuning_sweep_lab.py`): tune dispatch and gating only after field divergence is confirmed; reject solver failures and weak-gain/high-communication settings.
5. **Assignment-method comparison** (`run_assignment_method_comparison_lab.py`, `plot_assignment_method_comparison_lab.py`, optional): run only if solver choice still matters after the main tuning sweep.
6. **Robot scaling / long-horizon confirmation** (`run_robot_scaling_experiment.py`): confirm exposure gains grow with robot count, response does not collapse, communication stays controlled, and model-scored deterring gain rises.
