# Tuning Sweep Summary (Current Results)

- Scenarios evaluated: 27
- Methods: cbba, frozen_greedy, hungarian

## Mean over scenarios (proposed vs prediction-only)

| method | exposure improve % | response improve % | comm increase % |
|---|---:|---:|---:|
| cbba | 0.099 | 0.717 | 79.218 |
| frozen_greedy | -0.053 | 1.050 | 81.128 |
| hungarian | 0.569 | -1.793 | 81.164 |

## Best scenario per method (lexicographic: exposure, response, comm, runtime)

| method | scenario | exposure improve % | response improve % | comm increase % | runtime ms |
|---|---|---:|---:|---:|---:|
| cbba | d0_s0.5_rp45 | 0.863 | 4.933 | 86.217 | 4.945 |
| frozen_greedy | d0.005_s0_rp45 | 1.281 | 5.376 | 67.638 | 0.782 |
| hungarian | d0.005_s0.5_rp90 | 1.465 | 2.092 | 74.305 | 1.603 |
