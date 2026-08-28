# Workspace Layout

This repository is organized so the top level stays focused on the runtime core, while supporting scripts live in purpose-specific folders.

## Top-Level Rule

Keep only the simulation/runtime modules that are imported broadly at the repository root:

- `DeterrentSystem.py`
- `DeterrentSystem_simple_tasks.py`
- `Robot.py`
- `SESTPP.py`
- `TaskGenerator.py`
- `ZonePartitioner.py`
- `planner_*.py`
- `system_*.py`
- config/loading helpers such as `calibration_config.py` and `config_loader.py`

## Folder Guide

- `configs/`: JSON configs and config documentation
- `demos/`: interactive or visual demos
- `diagnostics/`: debugging and subsystem-inspection scripts
- `docs/`: design notes, experiment instructions, issue tracking, and workspace docs
- `experiments/`: experiment runners and benchmark entrypoints
- `habituation_stl/`: reusable STL robustness, habituation, and reference-ladder implementation
- `exploration/`: focused exploration variants and exploratory outputs
- `labs/`: isolated lab variants used for method development
- `plots/`: plotting/report-generation scripts
- `results/`: generated outputs, reports, metrics, and figures
- `sestpp_isolation/`: isolated SESTPP validation scripts/results
- `simplification/`: simplification stages and comparisons
- `testbench/`: benchmark harness and configs
- `tests/`: automated tests
- `telemetry_live/`: live telemetry artifacts for dashboards/demos

## Run Patterns

Use module execution for organized script folders:

- `python -m experiments.run_24h_experiment_parallel`
- `python experiments\run_habituation_stl_production_ladder.py --help`
- `python -m demos.demo_optimal_proposed`
- `python -m plots.plot_experiment_results`
- `python -m diagnostics.diagnostic_compare_systems`

This avoids ambiguity about relative imports after the reorganization.

## Habituation STL Artifacts

The production STL integration uses code in both the runtime root and `habituation_stl/`.

Primary documentation:

- `docs/STL_THEORY_AND_INTEGRATION_AUDIT.md`
- `docs/HABITUATION_STL_CONFIRMATORY_RESULTS.md`
- `docs/habituation_stl_completion_plan.md`
- `habituation_stl/README_INTEGRATION.md`

Primary result locations:

- `results/testbench/habituation_stl_revised_calibration_1800s_3seed/`
- `results/testbench/habituation_stl_revised_confirm_with_b2_1800s_10seed/`
- B1/B3/B4-only confirmatory run: `results/testbench/habituation_stl_revised_confirm_1800s_10seed/`
- Historical calibration: `results/testbench/habituation_stl_confirm_b1_b3_b4_1800s_10seed_v5/`
