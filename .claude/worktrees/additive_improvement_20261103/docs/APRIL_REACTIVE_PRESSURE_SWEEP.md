# April Reactive Pressure Sweep

This experiment is a diagnostic sweep for separating scenario pressure from dispatch behavior.

It keeps the April-aligned task semantics:

```text
predictive field -> patrol target -> direct detection -> reactive deterring task
```

Model-scored preventive deterring is disabled.

## What It Sweeps

The primary swept variable is the ground-truth bird arrival rate:

```text
mu_true
```

Default values:

```text
1e-6, 2e-6, 5e-6, 1e-5, 2e-5
```

The runner can also repeat the sweep across robot counts:

```text
6, 4, 3, 2
```

## Load Metrics

The existing metric is preserved:

```text
rho_assigned = lambda_assigned * mean(realized reactive service time) / N
```

where `lambda_assigned` is the assigned direct-detection task rate.

The new truth-side load metrics are:

```text
rho_truth = lambda_truth * tau_service / N
```

where `lambda_truth` is accepted ground-truth bird arrivals per second.

```text
rho_observed = lambda_observed * tau_service / N
```

where `lambda_observed` is ground-truth detections observed by the robots per second.

The intermediate observable load is:

```text
rho_observable = lambda_in_range * tau_service / N
```

where `lambda_in_range` counts truth arrivals that occurred within the owning robot's detection range before applying the detection probability.

All three load metrics use the configurable load window:

```text
reactive_load_factor_window_s = 120
```

This gives a two-minute local estimate instead of the older reservation-window estimate.

## Run Commands

Generate configs without running:

```powershell
python -m experiments.run_april_reactive_pressure_sweep --skip-run
```

Run the pilot sweep:

```powershell
python -m experiments.run_april_reactive_pressure_sweep --max-workers 3
```

Run a smaller calibration first:

```powershell
python -m experiments.run_april_reactive_pressure_sweep --robot-counts 2 --mu-values 1e-6 5e-6 1e-5 --max-workers 3
```

Run a very short smoke check:

```powershell
python -m experiments.run_april_reactive_pressure_sweep --robot-counts 2 --mu-values 1e-6 --duration-s 10 --warmup-s 0 --num-runs 1 --max-workers 1
```

Run the full five-seed sweep:

```powershell
python -m experiments.run_april_reactive_pressure_sweep --full --max-workers 3
```

## Output

Generated configs are written to:

```text
testbench/generated/april_reactive_pressure_sweep_pilot/
testbench/generated/april_reactive_pressure_sweep_full/
```

Results are written to:

```text
results/testbench/april_reactive_pressure_sweep_pilot/
results/testbench/april_reactive_pressure_sweep_full/
```

Each pressure point produces a normal testbench folder with:

```text
per_run_metrics.csv
per_run_timeseries.csv
summary_by_metric.csv
advantage_vs_reference.csv
time_metric_compare.png
```

## Interpretation

Use the load ladder as the main diagnostic:

```text
rho_truth -> rho_observable -> rho_observed -> rho_assigned
```

If `rho_truth` increases but `rho_observed` stays low, patrol coverage/perception is the bottleneck.

If `rho_observable` increases but `rho_observed` stays low, detection probability/noise is the bottleneck.

If `rho_observed` increases but `rho_assigned` stays low, task generation/admission/dispatch is the bottleneck.

If all three increase, then the reservation policy is being tested under real reactive pressure.
