# Vineyard Robot Deterrent System

This repository contains a simulation framework for multi-robot bird deterrence in vineyard-like environments.  
It implements an intervention-aware spatiotemporal intensity model, decentralized zone coordination, task generation/scoring, and experiment runners for thesis evaluation.

## What This Repo Includes

- **Online intensity model (`SESTPP.py`)**
  - Self-exciting trigger mass + inhibitory intervention mass
  - Separate temporal decays and spatial stamping
- **Robot + zone coordination (`Robot.py`, `ZonePartitioner.py`)**
  - Health-weighted zone partitioning and neighbor sharing
  - Boundary event exchange (detections + interventions)
- **Task generation and scoring (`TaskGenerator.py`)**
  - Candidate generation from hotspots
  - Benefit-vs-cost action scoring for patrol and deterrence
- **System simulation (`DeterrentSystem.py`)**
  - Ground-truth event process
  - Closed-loop intervention feedback
  - Metrics collection and baseline comparisons
- **Monitoring and telemetry (`telemetry_sim.py`, `streamlit_app.py`)**
  - Live telemetry CSV output
  - Streamlit dashboard with map/tasks/robot diagnostics
- **Experiment scripts**
  - `run_24h_experiment.py` (sequential sweep + thesis summary outputs)
  - `run_24h_experiment_parallel.py` (multiprocessing sweep)

## Quick Start

From repo root:

```powershell
python -m py_compile DeterrentSystem.py TaskGenerator.py SESTPP.py
```

Run the base 24h sweep (sequential):

```powershell
python run_24h_experiment.py
```

Run faster parallel sweep:

```powershell
python run_24h_experiment_parallel.py --profile fast --max-workers 12
```

Launch live dashboard (if telemetry is being flushed by a running sim):

```powershell
streamlit run streamlit_app.py
```

## Outputs

Typical experiment outputs include:

- baseline comparison CSVs (mean/variance metrics)
- per-run metrics CSVs
- experiment manifest CSVs (parameter traceability)
- thesis summary CSV/Markdown (sequential script)

## Experiments Documentation

Detailed instructions for experiment workflows and CLI options are in:

- `EXPERIMENTS.md`
