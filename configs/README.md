# YAML Config Examples

These example files show the supported YAML layout for the active runners.

Usage pattern:

```powershell
python run_sestpp_calibration_sweep.py
python compare_field_divergence_lab.py --config configs/compare_field_divergence_lab.yaml
python run_field_divergence_confirm_lab.py --config configs/run_field_divergence_confirm_lab.yaml
python run_field_divergence_filter_sweep_lab.py --config configs/run_field_divergence_filter_sweep_lab.yaml
python run_assignment_tuning_sweep_lab.py --config configs/run_assignment_tuning_sweep_lab.yaml
python run_assignment_method_comparison_lab.py --with-smoke-check
python plot_assignment_method_comparison_lab.py
python run_robot_scaling_experiment.py --profile fast
python run_24h_experiment_parallel.py --config configs/run_24h_experiment_parallel.yaml
```

## Thesis Staged Order

1. `python run_sestpp_calibration_sweep.py`
2. `python compare_field_divergence_lab.py --config configs/compare_field_divergence_lab.yaml`
3. `python run_field_divergence_confirm_lab.py --config configs/run_field_divergence_confirm_lab.yaml`
4. `python run_assignment_tuning_sweep_lab.py --config configs/run_assignment_tuning_sweep_lab.yaml`
5. `python run_assignment_method_comparison_lab.py --with-smoke-check` and `python plot_assignment_method_comparison_lab.py` if solver choice still needs a dedicated ablation
6. `python run_robot_scaling_experiment.py --profile fast`

Rules:
- CLI flags override YAML values.
- Unknown YAML keys fail fast.
- Nested YAML sections are supported; they are flattened into the existing runner argument names.
- Current YAML support covers runner-exposed parameters. It does not yet replace the full production simulator function signature.
- The confirm and assignment-tuning lab runners also accept `planner.profile: thesis_confirm` (alias `post_fix`) as a conservative post-fix preset; explicit YAML/CLI scalar overrides still win.
