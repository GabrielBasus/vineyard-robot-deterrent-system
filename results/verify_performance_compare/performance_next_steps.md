# Simplification Performance Comparison

- Stages: s1_risk_open_core, s5_current_thesis_profile
- Main/current reference stage: `s5_current_thesis_profile`
- Runs per baseline: `1`
- Horizon: `60.0` s
- Max workers: `2`

## Runtime

```text
                stage_key status  duration_s                                                   output_dir
        s1_risk_open_core     ok    4.972415         results\verify_performance_compare\s1_risk_open_core
s5_current_thesis_profile     ok    5.493993 results\verify_performance_compare\s5_current_thesis_profile
```

## Findings

- No stage shows a positive proposed-vs-prediction exposure win in this run.
- Highest model-scored preventive completions: `s1_risk_open_core` (1.000).
- Current main stage `s5_current_thesis_profile`: exposure vs prediction=0.000%, exposure vs reactive=0.000%, preventive completed=0.000, planner rejections=0.000.

## Recommended Next Steps

1. Focus on preventive dispatch/admission before adding more model-side complexity. The current main stage is generating preventive candidates but not converting them into completed model-scored actions.
1. Use `s1_risk_open_core` as the next preventive-yield debugging base. It currently completes more model-scored preventive actions than the main stage.
