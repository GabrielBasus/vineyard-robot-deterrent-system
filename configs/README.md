# YAML Config Examples

These example files show the supported YAML layout for the active runners.

Usage pattern:

```powershell
python -m experiments.run_sestpp_calibration_sweep
python -m experiments.compare_field_divergence_lab --config configs/compare_field_divergence_lab.yaml
python -m experiments.run_field_divergence_confirm_lab --config configs/run_field_divergence_confirm_lab.yaml
python -m experiments.run_field_divergence_filter_sweep_lab --config configs/run_field_divergence_filter_sweep_lab.yaml
python -m experiments.run_assignment_tuning_sweep_lab --config configs/run_assignment_tuning_sweep_lab.yaml
python -m experiments.run_assignment_method_comparison_lab --with-smoke-check
python -m plots.plot_assignment_method_comparison_lab
python -m experiments.run_robot_scaling_experiment --profile fast
python -m experiments.run_24h_experiment_parallel --config configs/run_24h_experiment_parallel.yaml
```

## Thesis Staged Order

1. `python -m experiments.run_sestpp_calibration_sweep`
2. `python -m experiments.compare_field_divergence_lab --config configs/compare_field_divergence_lab.yaml`
3. `python -m experiments.run_field_divergence_confirm_lab --config configs/run_field_divergence_confirm_lab.yaml`
4. `python -m experiments.run_assignment_tuning_sweep_lab --config configs/run_assignment_tuning_sweep_lab.yaml`
5. `python -m experiments.run_assignment_method_comparison_lab --with-smoke-check` and `python -m plots.plot_assignment_method_comparison_lab` if solver choice still needs a dedicated ablation
6. `python -m experiments.run_robot_scaling_experiment --profile fast`

Rules:
- CLI flags override YAML values.
- Unknown YAML keys fail fast.
- Nested YAML sections are supported; they are flattened into the existing runner argument names.
- Current YAML support covers runner-exposed parameters. It does not yet replace the full production simulator function signature.
- The confirm and assignment-tuning lab runners also accept `planner.profile: thesis_confirm` (alias `post_fix`) as a conservative post-fix preset; explicit YAML/CLI scalar overrides still win.
