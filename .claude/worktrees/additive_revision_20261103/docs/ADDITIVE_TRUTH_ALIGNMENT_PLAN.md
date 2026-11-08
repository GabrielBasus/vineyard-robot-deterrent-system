# Additive truth and estimator alignment

Status: implementation plan following the user's choice of the proposal and ACC additive formulation. No simulation source or running campaign is changed by this document.

## Authoritative target

- `proposal_stl.pdf`, PDF page 5, "Effective suppression in the ground-truth process," Eq. (6).
- `GB_ACC_2027_v2.pdf`, PDF page 2, Sec. II-C, Eqs. (7)-(9).
- Environmental intensity: `lambda_true = max(mu(x) * nu(t) + b(x,t) - u(x,t), 0)`.
- Suppression uses cue effectiveness immediately before application; depletion affects subsequent applications.
- This supersedes the suggested direction of retaining thinning and switching the estimator to multiplicative suppression. It does not authorize presenting either implementation as already evaluated.

## Decisions and dimensional specification

The additive equation is selected. Two details must be explicit before a new reference configuration is frozen:

1. Background demand (resolved): preserve existing physical demand. Keep `2e-5`, `1e-4`, `4e-4` as events per square metre per second per unit spatial weight, and correct the paper's per-cell label. Do not divide these values by cell area. This preserves exogenous background intensity, not necessarily accepted events or reactive demand after suppression changes.
2. Kernel amplitudes (resolved): the user approved a spatial Gaussian with unit integral on the full plane, the paper's unnormalized exponential time envelope, and beta as initial total suppressive rate in events/second before boundary loss. Existing beta numbers are an explicit new reference, not a conversion of the old dimensionless exponent. See `ADDITIVE_VERIFIED_CONTRACT.md` for the implemented discretization and verification scope.

Keep remaining numerical settings explicit and traceable. Distinguish estimator assumptions, physical truth parameters and policy settings. Any reference choice for a previously unspecified quantity must be documented before looking at comparative performance.

## Implementation sequence

1. Preserve current source/configuration identities, outputs and active campaign. Develop the additive environment in an isolated checkout and separate output namespace; retain the historical thinning mode for reproduction.
2. Define a single additive intensity contract covering background, accepted-event excitation, completed-action inhibition, positivity, integration area, spatial boundaries and update timing. Define the numerical simulation approximation and its time resolution explicitly.
3. Implement additive truth generation with coupled exogenous randomness. A final acceptance probability must reproduce the additive target; replacing `exp(-u)` by `1-u` is not sufficient. Accepted events alone produce future excitation.
4. Audit the existing unit-fixed additive estimator and every policy consumer: candidate forecasts, B2 valuation, B3/B4 STL counterfactuals, B5 cue scoring, historical feedback, committed schedules and continuation rollouts. Truth and estimator share functional conventions, while observations, estimated parameters and states remain separate.
5. Make all resolved settings explicit. Disable silent historical profile/quantile substitutions. Preserve complete truth intervention memory, correct stamp units and application-time effectiveness. Record any intentional communication differences.

## Verification before expensive searches

- Zero suppression, zero excitation, zero effectiveness and no-action reference cases.
- Single and overlapping interventions; nonnegative intensity; saturation at zero; recovery before application and depletion afterward.
- Matching-state comparisons between truth intensity evaluation and estimator/counterfactual evaluation, separately from tests with partial observations.
- Integrated kernel amplitude, grid-area scaling, boundary behavior and simulation time resolution.
- No simulator-state or truth-parameter leakage into online estimation or policy decisions.
- Deterministic replay, coupled random streams and checkpoint invalidation for the new source/configuration identities.
- Downstream predictions use the additive model throughout, including continuation worlds.
- Benchmark throughput and memory before allocating local or remote workers.

## Calibration and new evidence

Use the previously approved frozen-component inheritance: estimator under B1, B1, B2 and B3 tuning, B5 inheriting B1, and B4 inheriting B3. Calibration must use newly generated additive-environment recordings. Revisit search bounds where their units or parameter meanings have changed; freeze candidate definitions before selection. Preserve the paper STL requirements and report calibration failures.

Predeclare training, development and fresh evaluation seed roles. A reused seed number with a changed model is not an independent validation sample. Freeze configurations before confirmatory comparisons. Obtain B1-B5 results across the three demand conditions and both habituation settings before expanding to improvement variants. Report exposure and reactive-service tradeoffs with paired uncertainty; no policy is required to win.

Keep prior thinning-environment results labeled separately. Changing the environment invalidates reuse of its calibration and evaluation checkpoints for the additive study. Update the thesis equations and experimental descriptions only to reflect the implementation and results actually obtained.

## Execution boundary

The background-rate interpretation is resolved as above. Kernel/amplitude conventions and the simulator approximation require a concrete implementation specification before calibration begins. No new calibration or evaluation run is launched by this plan.
