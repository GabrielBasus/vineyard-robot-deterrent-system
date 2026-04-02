# Field Divergence Confirm

- Per-time CSV: `field_divergence_confirm_per_time.csv`
- Per-seed CSV: `field_divergence_confirm_per_seed.csv`
- Aggregate CSV: `field_divergence_confirm_aggregate.csv`
- Manifest: `field_divergence_confirm_manifest.json`

Key interpretation:
- `final_exposure_improve_pct > 0` means proposed lowered exposure relative to prediction-only.
- `final_response_improve_pct > 0` means proposed improved response time.
- Gate policy: `sprt_capacity`
- Low patrol-overlap metrics mean the proposed model is changing actual patrol behavior.
- Use the aggregate CSV CI95 values to judge whether single-seed improvements look robust.