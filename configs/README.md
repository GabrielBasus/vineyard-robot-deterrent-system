# YAML Config Examples

These example files show the supported YAML layout for the active runners.

Usage pattern:

```powershell
python compare_field_divergence_lab.py --config configs/compare_field_divergence_lab.yaml
python run_field_divergence_confirm_lab.py --config configs/run_field_divergence_confirm_lab.yaml
python run_field_divergence_filter_sweep_lab.py --config configs/run_field_divergence_filter_sweep_lab.yaml
python run_assignment_tuning_sweep_lab.py --config configs/run_assignment_tuning_sweep_lab.yaml
python run_24h_experiment_parallel.py --config configs/run_24h_experiment_parallel.yaml
```

Rules:
- CLI flags override YAML values.
- Unknown YAML keys fail fast.
- Nested YAML sections are supported; they are flattened into the existing runner argument names.
- Current YAML support covers runner-exposed parameters. It does not yet replace the full production simulator function signature.
