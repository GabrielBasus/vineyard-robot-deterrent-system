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

## Thesis Dispatch Demo Configs

The thesis dispatch visual comparisons use JSON config overlays for `python -m demos.demo_systems`.

Files:

- `configs/demo_thesis_dispatch_core3.json`
- `configs/demo_thesis_dispatch_reservation_sweep.json`
- `configs/demo_thesis_dispatch_random_ablation.json`

These configs inherit the base structure from `configs/demo_config.json` and only override the title, displayed metrics, and the three system variants.

Runbook:

- See `docs/THESIS_DISPATCH_RUNBOOK.md` for the thesis meaning of each variant, the exact demo commands, and the matching `testbench` / `experiments` entrypoints.

## Habituation-Aware STL Configuration

The STL proposal experiments are run through `experiments/run_habituation_stl_production_ladder.py` rather than the visual demo JSON overlays. This is intentional: the ladder needs paired habituation-on/off controls and baseline-specific STL clause settings.

The revised ladder uses fixed-cue controls for B1/B2/B3 and enables multi-cue variants only for `B4_res_stl_full_multicue`, which isolates the habituation-aware cue-variety mechanism.

Relevant simulator kwargs include:

- `predictive_utility_mode="stl_robustness"`
- `stl_active_clauses`
- `stl_E_star`
- `stl_T_cov_s`
- `stl_eta_min`
- `enable_habituation`
- `habituation_kappa`
- `habituation_T_rec_s`

See `docs/SYSTEM_VARIABLES.md` for the full variable reference and `docs/habituation_stl_completion_plan.md` for reproduction commands.
