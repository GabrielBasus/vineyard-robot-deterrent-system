# SESTPP Intervention Refactor Summary

## What changed

- `SESTPP.py` now keeps inhibition as persistent per-mode channels in `inhib_channels` instead of a single monolithic inhibition grid.
- Each intervention mode channel has its own decay constant in `inhib_channel_omegas`, and `advance_time(dt)` decays each channel with its own `omega_inhib`.
- `inhib_mass` is still exposed for downstream compatibility, but it is now a derived total field equal to the sum of all inhibition channels.
- `add_intervention_event(...)` now accepts `mode=` and stamps into that mode's channel while still using the existing `weight`, `sigma`, and `omega_inhib` inputs.
- The live intervention path was threaded through `Robot.py`, `DeterrentSystem.py`, `labs/DeterrentSystem_assignment_lab.py`, and `DeterrentSystem_simple_tasks.py` so existing deterrence mode labels propagate into `SESTPP`.

## Backward-compatibility notes

- Existing callers that omit `mode` still work. They are routed to the default inhibition channel.
- Existing code that reads `rob.m.inhib_mass` still works and now sees the summed inhibition across all modes.
- Existing constructor arguments are unchanged.
- `weight` remains the suppression-amplitude input. This is the natural place to pass thesis `beta_u`.

## API changes

- `OnlineSESTPP.add_intervention_event(...)` now supports the keyword argument `mode=`.
- `Robot.ingest_intervention_event(...)` now supports the keyword argument `mode=`.
- `Robot.intervention_boundary_events(...)` now supports `mode=`, `sigma=`, and `omega_inhib=` so relayed intervention messages preserve mode-specific parameters.

## Why this is more faithful to the thesis model

- The thesis model requires mode-dependent suppression with `beta_u`, `sigma_u`, and `omega_u`.
- Before this change, intervention events all collapsed into one inhibition state and one effective decay, because `omega_inhib` was only swapped temporarily during stamping.
- After this change, intervention modes keep distinct inhibitory state over time, spatial spread still comes from the event's `sigma`, and the total suppression used in `lam` is the sum across those persistent mode-specific channels.
