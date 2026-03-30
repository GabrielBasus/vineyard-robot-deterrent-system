# Assignment Methods Lab

This lab compares assignment methods in isolation from production code. It is intentionally implemented in lab-only files so the frozen simulation remains unchanged.

## Lab Scope

- Files used:
  - `TaskGenerator_lab.py`
  - `assignment_methods_lab.py`
  - `DeterrentSystem_assignment_lab.py`
  - `run_assignment_method_comparison_lab.py`
  - `plot_assignment_method_comparison_lab.py`
- Production files intentionally untouched:
  - `DeterrentSystem.py`
  - `TaskGenerator.py`
  - existing experiment runners

## Assignment API

`assignment_methods_lab.solve_assignment(method, request)` accepts:

- `tasks`: candidate tasks generated in the current cycle
- `robots`: candidate robot ids
- `capacity_by_robot`: per-robot open slots
- `score_fn(rid, task_idx) -> float`
- `eligible_fn(rid, task_idx) -> bool`
- `task_type_fn(task_idx) -> str` (optional)
- `neighbors_by_robot` (optional, used by decentralized CBBA)
- `cbba_max_rounds`, `cbba_epsilon` (CBBA consensus controls)

## Shared Utility / Cost Protocol

All methods consume the exact same per-pair utility from `DeterrentSystem_assignment_lab.py`:

`U(r, a) = score_task_assigner(r, a) - c_dist * d(r, a) - c_switch * I[switch_goal]`

Where:

- `score_task_assigner` is `TaskAssigner.score_robot_for_task(...)`
- `c_dist` is `assignment_distance_cost_per_m`
- `d(r, a)` is robot-to-task distance
- `c_switch` is `assignment_switch_penalty`
- `I[switch_goal]` is 1 when assignment changes a robot's active goal, else 0

This protocol is shared across frozen greedy, Hungarian, auction, and CBBA to keep comparisons method-fair.

Returns `AssignmentResult.primary_by_task_idx` for primary assignment only.

## Method Fidelity (Lab)

- `frozen_greedy`: deterministic sequential greedy reference that emulates current frozen behavior.
- `hungarian`: centralized linear assignment over expanded robot slots (`robot#slot`) maximizing total score via cost transform; debug output includes feasible/infeasible edge counts and unmatched tasks.
- `auction`: centralized epsilon-bidding emulation with deterministic tie and queue ordering.
- `cbba`: decentralized CBBA emulation over local neighbor communication rounds.
- `cbba_centralized`: legacy centralized CBBA emulation retained for ablation and sanity checks.

Secondary assignment for deterring tasks is intentionally shared and applied post-solver to avoid method-specific bias.

## CBBA Diagnostics

CBBA methods report:

- `rounds_to_convergence`
- `conflicts_resolved`
- `bid_updates`
- `message_passes` and `message_updates` (decentralized mode)
- `failures` (non-convergence and/or infeasible post-processing)

## Validation Checks

Implemented in `run_assignment_method_comparison_lab.py`:

- no robot exceeds capacity
- no task has more than one primary assignment
- ineligible pairs are never assigned
- determinism check for fixed request
- optional 10-minute integration smoke across all baselines and methods

## Experiment Outputs

Runner writes to `results/assignment_method_lab/`:

- `assignment_method_runs_lab.csv`
- `assignment_method_summary_lab.csv`
- `assignment_method_deltas_lab.csv`
- `assignment_method_manifest_lab.json`

Plotter writes to `results/assignment_method_lab/plots/`:

- exposure, response, and communication method comparisons
- proposed-minus-prediction deltas
- tradeoff scatter
- rank heatmaps
- `assignment_method_plots_summary_lab.md`

## Hungarian tuning sweep

Use `run_assignment_tuning_sweep_lab.py` to sweep assignment knobs while keeping production untouched.

Main knobs:

- `assignment_distance_cost_per_m`
- `assignment_switch_penalty`
- `task_replan_period_s`

Example:

`python run_assignment_tuning_sweep_lab.py --num-runs 8 --t-end 10800 --methods frozen_greedy,hungarian,cbba --distance-costs 0.0,0.002,0.005 --switch-penalties 0.0,0.2,0.5 --replan-periods 45,60,90 --outdir results/assignment_tuning_sweep_lab`

## Selection Rule

Winner is selected lexicographically using proposed vs prediction-only pairing:

1. max exposure improvement
2. then max response-time improvement
3. then min communication increase
4. then min solver runtime

Hard reject:

- unstable or infeasible assignment behavior
- communication increase greater than 100% with exposure gain below 0.5%

## Academic grounding

The compared classes align with established MRTA literature:

- Hungarian / linear assignment optimization
- auction-based multi-robot assignment
- CBBA (consensus-based bundle assignment)

References:

- Bertsekas, D. P. (1992). Auction algorithms for network flow problems.
- Choi, H.-L., Brunet, L., and How, J. P. (2009). Consensus-based decentralized auctions for robust task allocation.
- Gerkey, B. P., and Mataric, M. J. (2004). A formal analysis and taxonomy of task allocation in multi-robot systems.
