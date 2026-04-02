# SESTPP Monte Carlo Point Generation Lab

This experiment compares the current hotspot-based patrol-point generator against a
Monte Carlo generator that samples representative points from the SESTPP horizon field.

## Configuration
- Baselines: `prediction_only,proposed`
- Runs: `8` starting at seed `2026`
- Horizon: `300.0s`
- Monte Carlo rollouts: `64`
- Monte Carlo max events / rollout: `24`
- Monte Carlo uses excess field: `True`

## Summary
- `prediction_only` / `hotspots`: exposure=18122.025, response=105.704s, comm=550.5, forecast_hit=0.000
- `prediction_only` / `monte_carlo`: exposure=17835.760, response=115.947s, comm=462.8, forecast_hit=0.000
- `proposed` / `hotspots`: exposure=17953.480, response=162.346s, comm=727.0, forecast_hit=0.000
- `proposed` / `monte_carlo`: exposure=17792.024, response=144.039s, comm=889.5, forecast_hit=0.000

## Monte Carlo vs Hotspots
- `prediction_only`: exposure_improve=1.559%, response_improve=-10.591%, comm_change=-15.480%
- `proposed`: exposure_improve=0.900%, response_improve=10.713%, comm_change=24.067%
