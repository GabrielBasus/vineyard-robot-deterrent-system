# Robot Scaling Experiment

- Robot counts: [4, 6]
- Scenarios: ['S2_nominal']
- Runs per setting: 1
- Horizon [h]: 3.0

## Key outputs
- `robot_scaling_baseline_summary.csv`
- `robot_scaling_run_metrics.csv`
- `robot_scaling_pairwise_deltas.csv`
- `robot_scaling_delta_summary.csv`
- `01_exposure_improvement_vs_robot_count.png`
- `02_response_improvement_vs_robot_count.png`
- `03_comm_increase_vs_robot_count.png`
- `04_model_done_gain_vs_robot_count.png`
- `05_absolute_exposure_by_baseline_vs_robot_count.png`

## How to interpret
- Exposure curve should trend up (positive) for proposed-vs-prediction as robots increase.
- Response curve should not trend strongly negative.
- Communication curve should stay near/below +30% target if possible.
- Model-done gain should increase with robot count; if not, planner bottlenecks remain.