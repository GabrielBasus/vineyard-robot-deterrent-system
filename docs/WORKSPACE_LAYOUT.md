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
- `python -m demos.demo_optimal_proposed`
- `python -m plots.plot_experiment_results`
- `python -m diagnostics.diagnostic_compare_systems`

This avoids ambiguity about relative imports after the reorganization.
