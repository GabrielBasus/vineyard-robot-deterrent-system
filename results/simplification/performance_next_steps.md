# Simplification Performance Comparison

- Stages: s0_simple_tasks_core, s1_main_core, s2_direct_conflict, s3_persistence, s4_capacity_budget, s5_current_thesis_profile
- Main/current reference stage: `s5_current_thesis_profile`
- Runs per baseline: `5`
- Horizon: `7200.0` s
- Max workers: `6`

## Runtime

```text
                stage_key status  duration_s                                       output_dir
     s0_simple_tasks_core     ok  406.212244      results\simplification\s0_simple_tasks_core
             s1_main_core     ok 1277.334857              results\simplification\s1_main_core
       s2_direct_conflict     ok 1275.827812        results\simplification\s2_direct_conflict
           s3_persistence     ok 1279.030458            results\simplification\s3_persistence
       s4_capacity_budget     ok 1276.912027        results\simplification\s4_capacity_budget
s5_current_thesis_profile     ok 1248.485643 results\simplification\s5_current_thesis_profile
```

## Findings

- No stage shows a positive proposed-vs-prediction exposure win in this run.
- No stage completed any model-scored preventive actions in this run.
- Current main stage `s5_current_thesis_profile`: exposure vs prediction=0.000%, exposure vs reactive=-1.411%, preventive completed=0.000, planner rejections=415.400.

## Recommended Next Steps

1. This run is still too inconclusive for planner decisions. Increase `--t-end` and/or `--num-runs` before drawing subsystem conclusions.
1. Focus on preventive dispatch/admission before adding more model-side complexity. The current main stage is generating preventive candidates but not converting them into completed model-scored actions.
1. Treat `s1_main_core` as the next suspect control layer. It adds 81064.000 planner rejections over `s0_simple_tasks_core` without improving proposed-vs-prediction exposure or completed preventive actions.

## Secondary Observations

- `s5_current_thesis_profile` increases communication relative to `s4_capacity_budget` without an exposure gain.
