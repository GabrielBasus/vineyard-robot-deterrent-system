# Testbench

The testbench runs different system implementations under one shared scenario and one shared metric contract.

Supported target types:

- `simplification_stage`
- `exploration_variant`
- `current_mode`
- `repo_module`

Run the bundled example:

```powershell
python -m testbench.run_testbench --config testbench/example_config.json --max-workers 4
```

Relative `outputs.outdir` paths resolve from the repo root.

Write a fresh copy of the example config:

```powershell
python -m testbench.run_testbench --write-example-config testbench/my_config.json
```

Config structure:

```json
{
  "scenario": {
    "num_runs": 3,
    "seed_start": 123,
    "duration_s": 3600.0,
    "dt": 1.0,
    "fps": 1,
    "W": 500.0,
    "H": 500.0,
    "NX": 120,
    "NY": 96,
    "Nrobots": 6,
    "uav_fraction": 0.0,
    "task_replan_period_s": 45.0,
    "arrival_radius_m": 3.0,
    "hold_time_s": 20.0,
    "sample_every_s": 300.0
  },
  "outputs": {
    "outdir": "results/testbench/custom",
    "reference_system": "outline_core",
    "metrics": [
      "native_value_weighted_exposure",
      "native_mean_response_time_s",
      "native_birds_deterred_pct_last_hour"
    ],
    "scoreboard_metrics": [
      "native_value_weighted_exposure",
      "native_mean_response_time_s"
    ],
    "time_plot_metrics": [
      "native_value_weighted_exposure",
      "native_mean_response_time_s",
      "native_birds_deterred_pct_last_hour",
      "completed_deterring_total",
      "completed_tasks_total",
      "active_tasks"
    ]
  },
  "systems": [
    {
      "key": "outline_core",
      "type": "simplification_stage",
      "stage": "s1_risk_open_core"
    },
    {
      "key": "explore",
      "type": "exploration_variant",
      "variant": "row_local_priority_queue"
    },
    {
      "key": "main_native",
      "type": "repo_module",
      "repo": "main",
      "module": "DeterrentSystem",
      "params": {}
    }
  ]
}
```

Common metrics and native metrics can both be listed in `outputs.metrics`.
Use `outputs.time_plot_metrics` to choose which metrics appear in the time-series comparison plot.

Common metrics include:

- `completed_tasks_total`
- `completed_deterring_total`
- `completed_patrolling_total`
- `completed_tasks_per_hour`
- `mean_completion_latency_s`
- `tasks_per_km_travel`
- `mean_active_tasks`
- `final_active_tasks`

Native metrics include:

- `native_value_weighted_exposure`
- `native_mean_response_time_s`
- `native_truth_suppression_rate_last_hour`
- `native_birds_deterred_pct_last_hour`
- `native_truth_suppression_rate`
- `native_birds_deterred_pct`
- `native_boundary_message_count`
- `native_forecast_recall_at_k`
- `native_forecast_precision_at_k`
- `native_habituation_eta_mean`
- `native_habituation_eta_min`
- `native_habituation_eta_at_apply_mean`
- `native_habituation_variety_index`
- `native_stl_robustness_global_mean`
- `native_stl_robustness_global_min`
- `native_stl_robustness_exp`
- `native_stl_robustness_cov`
- `native_stl_robustness_hab`
- `native_truth_candidate_events`
- `native_truth_accepted_events`
- `native_truth_suppressed_events`
- `native_truth_suppression_effect_mean`
- `native_truth_suppression_effect_sum`

Artifacts:

- `per_run_metrics.csv`
- `per_run_timeseries.csv`
- `summary_by_metric.csv`
- `advantage_vs_reference.csv`
- `trajectory_compare.png`
- `time_metric_compare.png`
- `system_scoreboard.csv`
- `testbench_manifest.json`
- `report.md`

## Habituation-Aware STL Runs

The B0-B4 STL ladder uses dedicated experiment runners rather than generic JSON testbench configs because it needs paired habituation-on/off controls and system-specific STL clause settings.

Run the production ladder:

```powershell
C:\Users\gabri\AppData\Local\Programs\Python\Python310\python.exe experiments\run_habituation_stl_production_ladder.py --outdir results\testbench\habituation_stl_b0_b4_900s_10seed_v5 --duration-s 900 --num-runs 10 --seed-start 125 --warmup-s 0 --nx 120 --ny 96 --nrobots 6 --max-workers 2
```

Run the confirmatory B1/B3/B4 batch:

```powershell
C:\Users\gabri\AppData\Local\Programs\Python\Python310\python.exe experiments\run_habituation_stl_production_ladder.py --outdir results\testbench\habituation_stl_confirm_b1_b3_b4_1800s_10seed_v5 --duration-s 1800 --num-runs 10 --seed-start 125 --warmup-s 0 --nx 120 --ny 96 --nrobots 6 --systems B1_unc_legacy B3_res_stl_nohab B4_res_stl_full --max-workers 2
```

Summarize:

```powershell
C:\Users\gabri\AppData\Local\Programs\Python\Python310\python.exe experiments\summarize_habituation_stl_ladder.py --outdir results\testbench\habituation_stl_confirm_b1_b3_b4_1800s_10seed_v5
```

Current confirmed result documentation: `docs/HABITUATION_STL_CONFIRMATORY_RESULTS.md`.